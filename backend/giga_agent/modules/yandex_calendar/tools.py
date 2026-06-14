from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

import caldav
from icalendar import Calendar, Event
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.modules.yandex_calendar.auth import CALDAV_URL, get_calendar_creds

MAX_EVENTS = 50
PROVIDER = "yandex_calendar"


def agenda_payload(days: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Нормализованный payload агенды — фронт рендерит calendar_agenda по маркеру."""
    return {
        "widget": "calendar_agenda",
        "provider": PROVIDER,
        "days": days,
        "events": events,
    }


def _client(email: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(url=CALDAV_URL, username=email, password=password)


def _cal_name(cal: caldav.Calendar) -> str:
    try:
        return str(cal.get_display_name() or "Календарь")
    except Exception:  # noqa: BLE001
        return "Календарь"


def _parse_dt(value: str) -> dt.datetime:
    """ISO-строка → datetime. Принимает '2026-06-20T15:00' и '2026-06-20 15:00'."""
    return dt.datetime.fromisoformat(value.strip())


def _list_sync(email: str, password: str, days: int) -> list[dict[str, Any]]:
    principal = _client(email, password).principal()
    now = dt.datetime.now()
    end = now + dt.timedelta(days=days)
    out: list[dict[str, Any]] = []
    for cal in principal.calendars():
        name = _cal_name(cal)
        try:
            events = cal.search(start=now, end=end, event=True, expand=True)
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
    return out[:MAX_EVENTS]


def _create_sync(
    email: str, password: str, summary: str, start: str, end: str, description: str
) -> dict[str, Any]:
    principal = _client(email, password).principal()
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
    ev.add("dtstamp", dt.datetime.now())
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


def _delete_sync(email: str, password: str, uid: str) -> dict[str, Any]:
    principal = _client(email, password).principal()
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


@tool(parse_docstring=True)
async def calendar_list_events(runtime: ToolRuntime, days: int = 7) -> dict[str, Any]:
    """Возвращает ближайшие события Яндекс.Календаря по всем календарям.

    Args:
        days: На сколько дней вперёд смотреть (по умолчанию 7).
    """
    email, password = await get_calendar_creds(runtime)
    days = max(1, min(days, 90))
    events = await asyncio.to_thread(_list_sync, email, password, days)
    return agenda_payload(days, events)


@tool(parse_docstring=True)
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
    email, password = await get_calendar_creds(runtime)
    return await asyncio.to_thread(
        _create_sync, email, password, summary, start, end, description
    )


@tool(parse_docstring=True)
async def calendar_delete_event(runtime: ToolRuntime, uid: str) -> dict[str, Any]:
    """Удаляет событие Яндекс.Календаря по uid (требует подтверждения).

    Args:
        uid: Идентификатор события (поле uid из calendar_list_events).
    """
    email, password = await get_calendar_creds(runtime)
    return await asyncio.to_thread(_delete_sync, email, password, uid)
