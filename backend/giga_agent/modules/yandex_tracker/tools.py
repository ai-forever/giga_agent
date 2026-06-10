from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.modules.tracker_base import board_payload, field, make_issue, single_payload
from giga_agent.modules.yandex_tracker.auth import get_tracker_auth

TRACKER_API = "https://api.tracker.yandex.net/v2"
PROVIDER = "yandex_tracker"

# Ограничение на размер описания задачи, отдаваемого модели, чтобы не забить
# контекст GigaChat (лимит блока функций жёсткий, экономим везде).
MAX_DESCRIPTION_CHARS = 2000

_RU_MONTHS = (
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


def _short_date(iso: str | None) -> str | None:
    """ISO-дата Трекера → «8 июн» / «8 июн 2025» (формат был на фронте)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    base = f"{dt.day} {_RU_MONTHS[dt.month - 1]}"
    return base if dt.year == datetime.now(timezone.utc).year else f"{base} {dt.year}"


def _headers(token: str, org_id: str) -> dict[str, str]:
    # Шлём оба заголовка организации: X-Cloud-Org-ID — для организаций Yandex
    # Cloud, X-Org-ID — для Яндекс 360. Трекер использует подходящий, лишний
    # игнорирует. Пользователю достаточно указать один org-id.
    return {
        "Authorization": f"OAuth {token}",
        "X-Cloud-Org-ID": org_id,
        "X-Org-ID": org_id,
        "Content-Type": "application/json",
    }


def _disp(value: Any) -> Any:
    """display-имя для ссылочных полей Трекера (status/assignee/priority/...)."""
    if isinstance(value, dict):
        return value.get("display") or value.get("key") or value.get("id")
    return value


def _trim_issue(item: dict[str, Any], *, with_description: bool = False) -> dict[str, Any]:
    """Только полезные модели поля — Трекер отдаёт очень жирные объекты."""
    queue = item.get("queue")
    out: dict[str, Any] = {
        "key": item.get("key"),
        "summary": item.get("summary"),
        "status": _disp(item.get("status")),
        "assignee": _disp(item.get("assignee")),
        "queue": queue.get("key") if isinstance(queue, dict) else queue,
        "priority": _disp(item.get("priority")),
        "updatedAt": item.get("updatedAt"),
    }
    if with_description:
        desc = item.get("description") or ""
        if len(desc) > MAX_DESCRIPTION_CHARS:
            desc = desc[:MAX_DESCRIPTION_CHARS] + "…"
        out["description"] = desc
    return {k: v for k, v in out.items() if v is not None}


def _to_issue(item: dict[str, Any], *, with_description: bool = False) -> dict[str, Any]:
    """Сырой объект Трекера → нормализованный Issue (фронт-контракт)."""
    queue = item.get("queue")
    tag = queue.get("key") if isinstance(queue, dict) else queue
    fields = [
        field(_disp(item.get("assignee")), icon="user", label="Исполнитель"),
        field(_disp(item.get("priority")), icon="flag", label="Приоритет"),
        field(_short_date(item.get("updatedAt")), icon="clock", label="Обновлено"),
    ]
    desc: str | None = None
    if with_description:
        raw = item.get("description") or ""
        if raw:
            desc = (
                raw[:MAX_DESCRIPTION_CHARS] + "…"
                if len(raw) > MAX_DESCRIPTION_CHARS
                else raw
            )
    return make_issue(
        key=item.get("key"),
        title=item.get("summary"),
        provider=PROVIDER,
        status=_disp(item.get("status")),
        description=desc,
        tag=tag,
        fields=[f for f in fields if f],
    )


@tool(parse_docstring=True)
async def tracker_search_issues(
    runtime: ToolRuntime,
    query: str | None = None,
    queue: str | None = None,
    assignee: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Ищет задачи в Яндекс.Трекере.

    Можно искать либо строкой запроса на языке Трекера (query), либо фильтрами
    по очереди/исполнителю/статусу. Возвращает краткий список задач.

    Args:
        query: Запрос на языке Трекера, например 'Queue: TEST AND Status: Open'.
        queue: Ключ очереди для фильтра, например "TEST".
        assignee: Логин исполнителя для фильтра.
        status: Статус для фильтра, например "open" или "closed".
        limit: Сколько задач вернуть (максимум 50).
    """
    token, org_id = await get_tracker_auth(runtime)
    body: dict[str, Any] = {}
    if query:
        body["query"] = query
    else:
        filt: dict[str, Any] = {}
        if queue:
            filt["queue"] = queue
        if assignee:
            filt["assignee"] = assignee
        if status:
            filt["status"] = status
        if filt:
            body["filter"] = filt
    if not body:
        return {
            "error": "Укажите query или хотя бы один фильтр (queue/assignee/status)."
        }
    params = {"perPage": min(limit, 50)}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TRACKER_API}/issues/_search",
            headers=_headers(token, org_id),
            params=params,
            json=body,
        )
        resp.raise_for_status()
        items = resp.json()
    return board_payload(PROVIDER, [_to_issue(i) for i in items])


@tool(parse_docstring=True)
async def tracker_get_issue(runtime: ToolRuntime, issue_key: str) -> dict[str, Any]:
    """Возвращает карточку задачи Яндекс.Трекера по её ключу.

    Args:
        issue_key: Ключ задачи, например "TEST-42".
    """
    token, org_id = await get_tracker_auth(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{TRACKER_API}/issues/{issue_key}",
            headers=_headers(token, org_id),
        )
        resp.raise_for_status()
        item = resp.json()
    return single_payload(PROVIDER, _to_issue(item, with_description=True))


@tool(parse_docstring=True)
async def tracker_create_issue(
    runtime: ToolRuntime,
    queue: str,
    summary: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Создаёт новую задачу в Яндекс.Трекере.

    Args:
        queue: Ключ очереди, в которой создать задачу, например "TEST".
        summary: Заголовок задачи.
        description: Описание задачи (необязательно).
    """
    token, org_id = await get_tracker_auth(runtime)
    body: dict[str, Any] = {"queue": queue, "summary": summary}
    if description:
        body["description"] = description
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TRACKER_API}/issues/",
            headers=_headers(token, org_id),
            json=body,
        )
        resp.raise_for_status()
        item = resp.json()
    return {"status": "created", **_trim_issue(item)}


@tool(parse_docstring=True)
async def tracker_update_issue(
    runtime: ToolRuntime,
    issue_key: str,
    summary: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Изменяет заголовок и/или описание задачи Яндекс.Трекера.

    Args:
        issue_key: Ключ задачи, например "TEST-42".
        summary: Новый заголовок (необязательно).
        description: Новое описание (необязательно).
    """
    token, org_id = await get_tracker_auth(runtime)
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if not body:
        return {"error": "Нечего менять: укажите summary и/или description."}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{TRACKER_API}/issues/{issue_key}",
            headers=_headers(token, org_id),
            json=body,
        )
        resp.raise_for_status()
        item = resp.json()
    return {"status": "updated", **_trim_issue(item)}


@tool(parse_docstring=True)
async def tracker_add_comment(
    runtime: ToolRuntime, issue_key: str, text: str
) -> dict[str, Any]:
    """Добавляет комментарий к задаче Яндекс.Трекера.

    Args:
        issue_key: Ключ задачи, например "TEST-42".
        text: Текст комментария.
    """
    token, org_id = await get_tracker_auth(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TRACKER_API}/issues/{issue_key}/comments",
            headers=_headers(token, org_id),
            json={"text": text},
        )
        resp.raise_for_status()
    return {"status": "commented", "issue_key": issue_key}


@tool(parse_docstring=True)
async def tracker_transition(
    runtime: ToolRuntime, issue_key: str, transition: str
) -> dict[str, Any]:
    """Переводит задачу Яндекс.Трекера в другой статус.

    Если переход указан неверно, возвращает список доступных переходов — выбери
    из него правильный id и вызови инструмент снова.

    Args:
        issue_key: Ключ задачи, например "TEST-42".
        transition: Идентификатор перехода, например "close" или "start_progress".
    """
    token, org_id = await get_tracker_auth(runtime)
    async with httpx.AsyncClient() as client:
        avail = await client.get(
            f"{TRACKER_API}/issues/{issue_key}/transitions",
            headers=_headers(token, org_id),
        )
        avail.raise_for_status()
        transitions = avail.json()
        ids = {t.get("id") for t in transitions}
        if transition not in ids:
            return {
                "error": f"Переход '{transition}' недоступен.",
                "available": [
                    {"id": t.get("id"), "display": t.get("display")}
                    for t in transitions
                ],
            }
        ex = await client.post(
            f"{TRACKER_API}/issues/{issue_key}/transitions/{transition}/_execute",
            headers=_headers(token, org_id),
            json={},
        )
        ex.raise_for_status()
    return {"status": "transitioned", "issue_key": issue_key, "transition": transition}
