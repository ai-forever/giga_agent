"""OAuth-провайдер Яндекс.Календаря (CalDAV поверх OAuth-токена).

Отдельное Яндекс-приложение со своими client_id/secret и доступом к Календарю
(scope ``calendar:all``); токен получаем обычным OAuth2-флоу и ходим им в
caldav.yandex.ru заголовком ``Authorization: OAuth <token>`` (как у Диска —
``auth_header_scheme="OAuth"``).

Client-креды читаются из окружения ``YANDEX_CALENDAR_CLIENT_ID`` /
``YANDEX_CALENDAR_CLIENT_SECRET`` — как и остальные Яндекс-сервисы, независимое
приложение (в conf.py не заносим).
"""

from __future__ import annotations

import os

from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

YANDEX_CALENDAR_PROVIDER_KEY = "yandex_calendar"
CALDAV_URL = "https://caldav.yandex.ru"
# Scope Яндекс.Календаря: `calendar:all` даёт полный доступ к календарю
# пользователя (CalDAV). Приложение должно иметь это право при регистрации.
CALENDAR_SCOPE: str | None = "calendar:all"


def yandex_calendar_client() -> tuple[str | None, str | None]:
    return (
        os.getenv("YANDEX_CALENDAR_CLIENT_ID"),
        os.getenv("YANDEX_CALENDAR_CLIENT_SECRET"),
    )


def yandex_calendar_configured() -> bool:
    client_id, client_secret = yandex_calendar_client()
    return bool(client_id and client_secret)


def build_yandex_calendar_provider() -> StaticOAuthProvider:
    client_id, client_secret = yandex_calendar_client()
    return StaticOAuthProvider(
        StaticOAuthConfig(
            key=YANDEX_CALENDAR_PROVIDER_KEY,
            label="Яндекс.Календарь",
            icon="https://www.google.com/s2/favicons?domain=calendar.yandex.ru&sz=64",
            auth_kind="oauth2",
            authorization_endpoint="https://oauth.yandex.ru/authorize",
            token_endpoint="https://oauth.yandex.ru/token",
            client_id=client_id,
            client_secret=client_secret,
            scope=CALENDAR_SCOPE,
            validate_url="https://login.yandex.ru/info?format=json",
            auth_header_scheme="OAuth",
        )
    )
