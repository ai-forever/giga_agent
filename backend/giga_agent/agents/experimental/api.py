"""HTTP-ручка активности экспериментального режима.

Отдаёт ЖИВОЙ лог активности хода (вызванные инструменты + строки-статусы),
который граф `giga_agent_experimental` копит в cashews по внешнему thread_id
(см. `graph._record_tools_from_snapshot` / `_record_status`). Нужна фронту, чтобы
во время активного рана открыть панель «Активность» по клику на «Думаю…»
(`ThinkingIndicator`). Завершённый маркер панель читает из встроенного снапшота,
без этой ручки.

Монтируется ядром под `{GIGA_AGENT_PREFIX_API}/experimental` (см.
`ExperimentalModule.get_api_router` и base.py) → `GET /agent/experimental/activity/{thread_id}`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from giga_agent.agents.experimental.graph import _empty_activity, _get_activity
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import (
    AUTH_COOKIE_NAME,
    get_current_active_user,
    oauth2_scheme,
)
from giga_agent.utils.langgraph_sdk import client_session

router = APIRouter(tags=["experimental"])


def _bearer_token(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> str | None:
    """Сырой access-токен вызывающего (заголовок Authorization или auth-cookie)."""
    raw = token or request.cookies.get(AUTH_COOKIE_NAME)
    if raw and raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw


@router.get("/activity/{thread_id}")
async def get_activity(
    thread_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
) -> dict:
    """Живой лог активности треда. 404, если тред недоступен вызывающему."""
    _ = current_user  # владение проверяется ниже проброшенным токеном
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Could not validate credentials"
        )

    # Проверка владения: тред читается только владельцем (langgraph-auth). Нет
    # доступа → 404 (не палим существование чужого треда).
    langgraph_config = {"configurable": {"langgraph_auth_user": {"token": token}}}
    try:
        async with client_session(langgraph_config) as client:
            await client.threads.get(thread_id)
    except Exception as exc:  # noqa: BLE001 — любой сбой = нет доступа
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found") from exc

    return await _get_activity(thread_id) or _empty_activity()
