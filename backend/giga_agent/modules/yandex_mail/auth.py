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


async def get_mail_auth(runtime: ToolRuntime) -> tuple[str, str]:
    """Возвращает (email, access_token) текущего пользователя для XOAUTH2.

    Токен берётся из общего OAuth-стора (с авто-refresh, как Диск/Трекер).
    Адрес ящика определяется через Яндекс ID (`login.yandex.ru/info`) —
    он нужен для строки XOAUTH2 (`user=<email>`).
    """
    token = await oauth_tokens.get_valid_access_token(runtime, "yandex_mail")
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
    return email, token


def xoauth2_bytes(email: str, token: str) -> bytes:
    """Строка авторизации XOAUTH2 для IMAP/SMTP Яндекса."""
    return f"user={email}\x01auth=Bearer {token}\x01\x01".encode()
