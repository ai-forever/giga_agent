"""Тулы Яндекс.Календаря поверх OAuth-токена.

CalDAV-клиент строится по OAuth-токену (заголовок ``Authorization: OAuth``).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

import caldav
from icalendar import Calendar, Event
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.core.agent.tool_policy import (
    ToolConfirmation,
    ToolEffect,
    tool_extras,
)
from giga_agent.core.agent.tool_results import build_widget_tool_message
from giga_agent.core.time import default_tz
from giga_agent.modules.integrations.widget_hint import with_widget_note
from giga_agent.modules.integrations.yandex_calendar.auth import get_calendar_token
from giga_agent.modules.integrations.yandex_calendar.provider import CALDAV_URL

MAX_EVENTS = 50
MAX_MONTH_EVENTS = 200
PROVIDER = "yandex_calendar"


def agenda_payload(days: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Нормализованный payload агенды — фронт рендерит calendar_agenda по маркеру."""
    return {
        "widget": "calendar_agenda",
        "provider": PROVIDER,
        "days": days,
        "events": events,
    }


def month_payload(
    year: int, month: int, events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Payload месяца-грида — фронт рендерит calendar_month по маркеру."""
    return {
        "widget": "calendar_month",
        "provider": PROVIDER,
        "year": year,
        "month": month,
        "events": events,
    }


def _client(token: str) -> caldav.DAVClient:
    """CalDAV-клиент на OAuth-токене: Яндекс принимает ``Authorization: OAuth``."""
    return caldav.DAVClient(url=CALDAV_URL, headers={"Authorization": f"OAuth {token}"})


def _cal_name(cal: caldav.Calendar) -> str:
    try:
        return str(cal.get_display_name() or "Календарь")
    except Exception:  # noqa: BLE001
        return "Календарь"


def _parse_dt(value: str) -> dt.datetime:
    """ISO-строка → aware datetime. Принимает '2026-06-20T15:00' и
    '2026-06-20 15:00'. Наивное время трактуем в проектной TZ (default_tz) — так
    же, как агент видит «текущее время» и как cron читает расписания."""
    parsed = dt.datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_tz())


def _demojibake(text: str) -> str:
    """Чинит двойное кодирование текста (UTF-8, прочитанный как cp1252/latin-1):
    'Ð”Ð\xa0 ...' → 'ДР ...'. Аргументы тула иногда доезжают уже в таком виде, и
    событие сохраняется с крокозябрами. Строгий re-decode служит защитой: чистый
    юникод (кириллица не кодируется в cp1252/latin-1) и обычный текст остаются как
    есть — чиним только то, что реально является mojibake."""
    if not text:
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            repaired = text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text:
            return repaired
    return text


def _search_range(
    token: str, start: dt.datetime, end: dt.datetime, cap: int
) -> list[dict[str, Any]]:
    """События во временном окне [start, end) по всем календарям пользователя."""
    principal = _client(token).principal()
    out: list[dict[str, Any]] = []
    for cal in principal.calendars():
        name = _cal_name(cal)
        try:
            events = cal.search(start=start, end=end, event=True, expand=True)
        except Exception:  # noqa: BLE001 — календарь мог не поддержать expand
            continue
        for ev in events:
            comp = ev.icalendar_component
            if comp is None:
                continue
            ds = comp.get("dtstart")
            de = comp.get("dtend")
            out.append(
                {
                    "uid": str(comp.get("uid", "")),
                    "calendar": name,
                    "summary": str(comp.get("summary", "(без названия)")),
                    "start": ds.dt.isoformat() if ds else None,
                    "end": de.dt.isoformat() if de else None,
                    "location": str(comp.get("location", "")) or None,
                }
            )
    out.sort(key=lambda e: e.get("start") or "")
    return out[:cap]


def _list_sync(token: str, days: int) -> list[dict[str, Any]]:
    now = dt.datetime.now(default_tz())
    return _search_range(token, now, now + dt.timedelta(days=days), MAX_EVENTS)


def _month_sync(token: str, year: int, month: int) -> list[dict[str, Any]]:
    tz = default_tz()
    start = dt.datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end = dt.datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end = dt.datetime(year, month + 1, 1, tzinfo=tz)
    return _search_range(token, start, end, MAX_MONTH_EVENTS)


def _create_sync(
    token: str, summary: str, start: str, end: str, description: str
) -> dict[str, Any]:
    summary = _demojibake(summary)
    description = _demojibake(description)
    principal = _client(token).principal()
    cals = principal.calendars()
    if not cals:
        return {"error": "Нет доступных календарей."}
    target = cals[0]  # основной календарь («Мои события»)
    cal = Calendar()
    cal.add("prodid", "-//giga_agent//yandex_calendar//RU")
    cal.add("version", "2.0")
    ev = Event()
    uid = f"{uuid.uuid4()}@giga-agent"
    ev.add("uid", uid)
    ev.add("summary", summary)
    ev.add("dtstart", _parse_dt(start))
    ev.add("dtend", _parse_dt(end))
    if description:
        ev.add("description", description)
    ev.add("dtstamp", dt.datetime.now(dt.timezone.utc))
    cal.add_component(ev)
    target.save_event(cal.to_ical().decode("utf-8"))
    return {
        "status": "created",
        "uid": uid,
        "calendar": _cal_name(target),
        "summary": summary,
        "start": start,
        "end": end,
    }


def _delete_sync(token: str, uid: str) -> dict[str, Any]:
    principal = _client(token).principal()
    for cal in principal.calendars():
        try:
            events = cal.events()
        except Exception:  # noqa: BLE001
            continue
        for ev in events:
            comp = ev.icalendar_component
            if comp is not None and str(comp.get("uid", "")) == uid:
                ev.delete()
                return {"status": "deleted", "uid": uid, "calendar": _cal_name(cal)}
    return {"error": f"Событие {uid} не найдено."}


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def calendar_list_events(runtime: ToolRuntime, days: int = 7) -> dict[str, Any]:
    """Возвращает ближайшие события Яндекс.Календаря по всем календарям.

    Args:
        days: На сколько дней вперёд смотреть (по умолчанию 7).
    """
    token = await get_calendar_token(runtime)
    days = max(1, min(days, 90))
    events = await asyncio.to_thread(_list_sync, token, days)
    return build_widget_tool_message(
        await with_widget_note(agenda_payload(days, events), runtime), runtime=runtime
    )


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def calendar_month(
    runtime: ToolRuntime, year: int = 0, month: int = 0
) -> dict[str, Any]:
    """Возвращает события за весь месяц (для месяц-грида).

    Вызывай, когда просят показать месяц целиком («покажи июнь», «календарь на
    месяц»). Без аргументов — текущий месяц.

    Args:
        year: Год (например 2026). 0 = текущий.
        month: Месяц 1–12. 0 = текущий.
    """
    token = await get_calendar_token(runtime)
    now = dt.datetime.now(default_tz())
    y = year or now.year
    m = month or now.month
    if not (1 <= m <= 12):
        return {"error": "Месяц должен быть 1–12."}
    events = await asyncio.to_thread(_month_sync, token, y, m)
    return build_widget_tool_message(
        await with_widget_note(month_payload(y, m, events), runtime), runtime=runtime
    )


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.ALWAYS,
    ),
)
async def calendar_create_event(
    runtime: ToolRuntime,
    summary: str,
    start: str,
    end: str,
    description: str = "",
) -> dict[str, Any]:
    """Создаёт событие в основном календаре Яндекс.Календаря.

    Создание требует подтверждения пользователя.

    Args:
        summary: Название события.
        start: Начало в ISO, например "2026-06-20T15:00".
        end: Конец в ISO, например "2026-06-20T16:00".
        description: Описание (необязательно).
    """
    token = await get_calendar_token(runtime)
    return await asyncio.to_thread(
        _create_sync, token, summary, start, end, description
    )


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.DESTRUCTIVE,
        confirmation=ToolConfirmation.ALWAYS,
    ),
)
async def calendar_delete_event(runtime: ToolRuntime, uid: str) -> dict[str, Any]:
    """Удаляет событие Яндекс.Календаря по uid (требует подтверждения).

    Args:
        uid: Идентификатор события (поле uid из calendar_list_events).
    """
    token = await get_calendar_token(runtime)
    return await asyncio.to_thread(_delete_sync, token, uid)
