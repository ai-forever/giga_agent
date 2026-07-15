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

from giga_agent.agents.experimental.graph import (
    _empty_activity,
    _forget_activity,
    _forget_statuses,
    _get_activity,
)
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


@router.delete("/thread/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
) -> None:
    """Удалить экспериментальный тред ВМЕСТЕ со скрытым inner-тредом.

    Обёртка `giga_agent_experimental` гоняет реального агента в отдельном скрытом
    треде (`inner_thread_id` в state внешнего треда). Прямое удаление внешнего
    треда через SDK inner-тред не трогает — он осиротевает. Поэтому фронт в
    experimental-режиме удаляет тред через эту ручку: она достаёт `inner_thread_id`
    из state внешнего треда и удаляет оба (+ чистит кэш активности/статусов).

    Владение проверяется проброшенным токеном вызывающего (langgraph-auth):
    `get_state`/`delete` чужого треда упадут → 404 (не палим существование чужого).
    """
    _ = current_user  # владение проверяется ниже проброшенным токеном
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Could not validate credentials"
        )

    langgraph_config = {"configurable": {"langgraph_auth_user": {"token": token}}}
    async with client_session(langgraph_config) as client:
        # get_state и подтверждает владение, и отдаёт inner_thread_id/run-id'ы.
        try:
            snap = await client.threads.get_state(thread_id)
        except Exception as exc:  # noqa: BLE001 — любой сбой = нет доступа
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found") from exc

        values = snap.get("values") or {}
        inner_thread_id = values.get("inner_thread_id")
        inner_run_id = values.get("inner_run_id")
        activity_id = values.get("activity_id")

        # Сначала inner-тред (best-effort — мог быть уже удалён/не создан), затем
        # внешний. Провал удаления inner не должен блокировать удаление внешнего.
        if isinstance(inner_thread_id, str) and inner_thread_id:
            try:
                await client.threads.delete(inner_thread_id)
            except Exception:  # noqa: BLE001
                pass

        await client.threads.delete(thread_id)

    # Презентационный кэш (в state не живёт) — чистим best-effort.
    await _forget_activity(thread_id)
    for run_id in (inner_run_id, activity_id):
        if isinstance(run_id, str) and run_id:
            await _forget_statuses(run_id)
