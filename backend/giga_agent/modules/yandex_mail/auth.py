from __future__ import annotations

import httpx
from langchain.tools import ToolRuntime

from giga_agent.models.users import UserShort
from giga_agent.modules.yandex_oauth import tokens as oauth_tokens

# Имя access-секрета (совпадает с тем, что заполняет общий OAuth-флоу и/или
# ручной ввод). is_enabled/тулы ориентируются на его наличие.
YANDEX_MAIL_ACCESS_TOKEN = "YANDEX_MAIL_ACCESS_TOKEN"

IMAP_HOST = "imap.yandex.ru"
IMAP_PORT = 993
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT = 465


def has_mail_token(user: UserShort | None) -> bool:
    if user is None:
        return False
    return oauth_tokens.is_connected(user, "yandex_mail")


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
    """Возвращает (email, access_token) текущего пользователя для XOAUTH2.

    Токен берётся из общего OAuth-стора (с авто-refresh, как Диск/Трекер).
    """
    token = await oauth_tokens.get_valid_access_token(runtime, "yandex_mail")
    return await _email_for_token(token), token


async def get_mail_auth_for_user(user) -> tuple[str, str]:
    """Версия для REST-эндпоинтов (виджет): пользователь уже из FastAPI-зависимости."""
    token = await oauth_tokens.get_valid_access_token_for_user(user, "yandex_mail")
    return await _email_for_token(token), token


def xoauth2_bytes(email: str, token: str) -> bytes:
    """Строка авторизации XOAUTH2 для IMAP/SMTP Яндекса."""
    return f"user={email}\x01auth=Bearer {token}\x01\x01".encode()
