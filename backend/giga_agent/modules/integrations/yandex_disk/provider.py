"""OAuth-провайдер Яндекс.Диска.

Отдельное Яндекс-приложение под свой scope (`cloud_api:disk.*`). Client-креды
читаются напрямую из окружения (`YANDEX_DISK_CLIENT_ID`/`_SECRET`) — в conf.py их
не заносим, каждый сервис Яндекса — независимое приложение.
"""

from __future__ import annotations

import os

from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

YANDEX_DISK_PROVIDER_KEY = "yandex_disk"
DISK_SCOPE = "cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info"


def yandex_disk_client() -> tuple[str | None, str | None]:
    return os.getenv("YANDEX_DISK_CLIENT_ID"), os.getenv("YANDEX_DISK_CLIENT_SECRET")


def yandex_disk_configured() -> bool:
    client_id, client_secret = yandex_disk_client()
    return bool(client_id and client_secret)


def build_yandex_disk_provider() -> StaticOAuthProvider:
    client_id, client_secret = yandex_disk_client()
    return StaticOAuthProvider(
        StaticOAuthConfig(
            key=YANDEX_DISK_PROVIDER_KEY,
            label="Яндекс.Диск",
            icon="https://www.google.com/s2/favicons?domain=disk.yandex.ru&sz=64",
            auth_kind="oauth2",
            authorization_endpoint="https://oauth.yandex.ru/authorize",
            token_endpoint="https://oauth.yandex.ru/token",
            client_id=client_id,
            client_secret=client_secret,
            scope=DISK_SCOPE,
            validate_url="https://login.yandex.ru/info?format=json",
            auth_header_scheme="OAuth",
        )
    )
