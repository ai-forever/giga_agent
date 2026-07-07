from __future__ import annotations

import uuid

import httpx
from langchain.tools import ToolRuntime

from giga_agent.core.integrations.service import get_access_token
from giga_agent.models.users import UserShort
from giga_agent.modules.integrations.yandex_mail.provider import (
    YANDEX_MAIL_PROVIDER_KEY,
)
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

IMAP_HOST = "imap.yandex.ru"
IMAP_PORT = 993
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT = 465


def _runtime_user_id(runtime: ToolRuntime) -> uuid.UUID:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


async def _email_for_token(token: str) -> str:
    """Адрес ящика по токену через Яндекс ID — нужен для строки XOAUTH2."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://login.yandex.ru/info",
            headers={"Authorization": f"OAuth {token}"},
            params={"format": "json"},
        )
        resp.raise_for_status()
        info = resp.json()
    email = info.get("default_email") or info.get("login")
    if not email:
        raise ValueError(
            "Не удалось определить адрес ящика. Убедитесь, что у токена есть "
            "доступ к Яндекс ID (scope login:email)."
        )
    return email


async def get_mail_auth(runtime: ToolRuntime) -> tuple[str, str]:
    """(email, access_token) текущего пользователя для XOAUTH2 (IMAP/SMTP)."""
    token = await get_access_token(_runtime_user_id(runtime), YANDEX_MAIL_PROVIDER_KEY)
    return await _email_for_token(token), token


async def get_mail_auth_for_user(user: UserShort) -> tuple[str, str]:
    """Версия для REST-эндпоинтов (виджет mail_inbox)."""
    token = await get_access_token(user.id, YANDEX_MAIL_PROVIDER_KEY)
    return await _email_for_token(token), token


def xoauth2_bytes(email: str, token: str) -> bytes:
    """Строка авторизации XOAUTH2 для IMAP/SMTP Яндекса."""
    return f"user={email}\x01auth=Bearer {token}\x01\x01".encode()
