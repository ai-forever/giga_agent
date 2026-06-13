"""REST Яндекс.Почты для mail_inbox-виджета: чтение тела письма и обновление
списка без round-trip через модель. Авторизация — токен текущего пользователя
FastAPI (XOAUTH2 через общий OAuth-стор). Только чтение: отправка остаётся за
агентом (mail_send в confirm-гейте на деструктив).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.yandex_mail.auth import get_mail_auth_for_user
from giga_agent.modules.yandex_mail.tools import (
    MAX_LIMIT,
    _read_sync,
    _search_sync,
    inbox_payload,
)

router = APIRouter(tags=["yandex_mail"])


async def _auth(user: UserShort) -> tuple[str, str]:
    try:
        return await get_mail_auth_for_user(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/messages")
async def list_messages(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    folder: str = "INBOX",
    limit: int = 15,
) -> dict[str, Any]:
    """Список писем папки — для обновления/смены папки в виджете."""
    email_addr, token = await _auth(current_user)
    limit = max(1, min(limit, MAX_LIMIT))
    items = await asyncio.to_thread(_search_sync, email_addr, token, folder, limit)
    return inbox_payload(folder, items)


@router.get("/read")
async def read_message(
    message_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    folder: str = "INBOX",
) -> dict[str, Any]:
    """Тело письма целиком — по клику на письмо в виджете."""
    email_addr, token = await _auth(current_user)
    return await asyncio.to_thread(_read_sync, email_addr, token, folder, message_id)
