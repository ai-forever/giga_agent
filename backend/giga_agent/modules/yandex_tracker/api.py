"""REST-эндпоинты Яндекс.Трекера для интерактивных GenUI-виджетов.

Эти ручки нужны, чтобы карточки задач в чате могли менять статус «по кнопке»
напрямую, без round-trip через модель: фронт дёргает их с оптимистик-апдейтом.
Логика и заголовки переиспользуются из tools.py — здесь только тонкий HTTP-слой
поверх Tracker REST с авторизацией через пользователя FastAPI.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.yandex_tracker.auth import get_tracker_auth_for_user
from giga_agent.modules.yandex_tracker.tools import (
    TRACKER_API,
    _disp,
    _headers,
    _trim_issue,
)

router = APIRouter(tags=["yandex_tracker"])


def _auth(user: UserShort | None) -> dict[str, str]:
    """Заголовки авторизации Трекера для текущего пользователя или 400."""
    try:
        token, org_id = get_tracker_auth_for_user(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _headers(token, org_id)


def _raise_for_tracker(exc: httpx.HTTPStatusError) -> None:
    """Пробрасываем ошибку Трекера наружу, сохраняя статус и тело."""
    detail: Any
    try:
        detail = exc.response.json()
    except Exception:  # noqa: BLE001 — тело может быть не-JSON
        detail = exc.response.text or "Ошибка Яндекс.Трекера"
    raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc


@router.get("/issues/{issue_key}/transitions")
async def list_transitions(
    issue_key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Доступные переходы статуса для задачи — лениво, по клику на бейдж."""
    headers = _auth(current_user)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{TRACKER_API}/issues/{issue_key}/transitions", headers=headers
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _raise_for_tracker(exc)
        transitions = resp.json()
    return {
        "transitions": [
            {
                "id": t.get("id"),
                "display": t.get("display"),
                "to": _disp(t.get("to")),
            }
            for t in transitions
        ]
    }


@router.post("/issues/{issue_key}/transitions/{transition_id}")
async def execute_transition(
    issue_key: str,
    transition_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Исполняет переход и возвращает свежую карточку (для подтверждения UI)."""
    headers = _auth(current_user)
    async with httpx.AsyncClient() as client:
        ex = await client.post(
            f"{TRACKER_API}/issues/{issue_key}/transitions/{transition_id}/_execute",
            headers=headers,
            json={},
        )
        try:
            ex.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _raise_for_tracker(exc)
        # Перечитываем задачу: ответ _execute не всегда содержит новый статус.
        fresh = await client.get(
            f"{TRACKER_API}/issues/{issue_key}", headers=headers
        )
        try:
            fresh.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _raise_for_tracker(exc)
        item = fresh.json()
    return {"status": "transitioned", "issue": _trim_issue(item)}


@router.get("/issues/{issue_key}")
async def get_issue(
    issue_key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Свежая карточка задачи — для ручного refresh виджета."""
    headers = _auth(current_user)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{TRACKER_API}/issues/{issue_key}", headers=headers
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _raise_for_tracker(exc)
        item = resp.json()
    return {"issue": _trim_issue(item, with_description=True)}
