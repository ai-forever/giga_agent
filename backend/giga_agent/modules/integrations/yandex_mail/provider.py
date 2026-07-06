"""OAuth-провайдер Яндекс.Почты.

Отдельное Яндекс-приложение под mail-scope (Яндекс требует отдельного одобрения
для почты). `login:email` — чтобы получить адрес ящика для строки XOAUTH2.
Client-креды читаются напрямую из окружения (`YANDEX_MAIL_CLIENT_ID`/`_SECRET`).
"""

from __future__ import annotations

import os

from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

YANDEX_MAIL_PROVIDER_KEY = "yandex_mail"
# imap_full — чтение, smtp — отправка, login:email — адрес ящика для XOAUTH2.
MAIL_SCOPE = "mail:imap_full mail:smtp login:email"


def yandex_mail_client() -> tuple[str | None, str | None]:
    return os.getenv("YANDEX_MAIL_CLIENT_ID"), os.getenv("YANDEX_MAIL_CLIENT_SECRET")


def yandex_mail_configured() -> bool:
    client_id, client_secret = yandex_mail_client()
    return bool(client_id and client_secret)


def build_yandex_mail_provider() -> StaticOAuthProvider:
    client_id, client_secret = yandex_mail_client()
    return StaticOAuthProvider(
        StaticOAuthConfig(
            key=YANDEX_MAIL_PROVIDER_KEY,
            label="Яндекс.Почта",
            icon="https://www.google.com/s2/favicons?domain=mail.yandex.ru&sz=64",
            auth_kind="oauth2",
            authorization_endpoint="https://oauth.yandex.ru/authorize",
            token_endpoint="https://oauth.yandex.ru/token",
            client_id=client_id,
            client_secret=client_secret,
            scope=MAIL_SCOPE,
            validate_url="https://login.yandex.ru/info?format=json",
            auth_header_scheme="OAuth",
        )
    )
