"""OAuth-провайдер Яндекс.Трекера.

Отдельное Яндекс-приложение под scope `tracker:read tracker:write`. Client-креды
читаются напрямую из окружения (`YANDEX_TRACKER_CLIENT_ID`/`_SECRET`). Сверх OAuth
Трекеру всегда нужен `YANDEX_TRACKER_ORG_ID` — это ручной секрет модуля (в OAuth
организации нет).
"""

from __future__ import annotations

import os

from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

YANDEX_TRACKER_PROVIDER_KEY = "yandex_tracker"
TRACKER_SCOPE = "tracker:read tracker:write"


def yandex_tracker_client() -> tuple[str | None, str | None]:
    return (
        os.getenv("YANDEX_TRACKER_CLIENT_ID"),
        os.getenv("YANDEX_TRACKER_CLIENT_SECRET"),
    )


def yandex_tracker_configured() -> bool:
    client_id, client_secret = yandex_tracker_client()
    return bool(client_id and client_secret)


def build_yandex_tracker_provider() -> StaticOAuthProvider:
    client_id, client_secret = yandex_tracker_client()
    return StaticOAuthProvider(
        StaticOAuthConfig(
            key=YANDEX_TRACKER_PROVIDER_KEY,
            label="Яндекс.Трекер",
            icon="https://www.google.com/s2/favicons?domain=tracker.yandex.ru&sz=64",
            auth_kind="oauth2",
            authorization_endpoint="https://oauth.yandex.ru/authorize",
            token_endpoint="https://oauth.yandex.ru/token",
            client_id=client_id,
            client_secret=client_secret,
            scope=TRACKER_SCOPE,
            validate_url="https://login.yandex.ru/info?format=json",
            auth_header_scheme="OAuth",
        )
    )
