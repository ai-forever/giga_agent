"""Provider registry: resolves a ``provider_key`` to an :class:`IntegrationProvider`.

Two sources:
- A static catalog built from config (Yandex OAuth, GitHub PAT, ...). These are
  the providers native agent modules declare a dependency on.
- MCP servers, resolved dynamically from the DB by ``mcp:<server_id>`` keys.
"""

from __future__ import annotations

import uuid

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.core.integrations.base import (
    IntegrationProvider,
    ManualField,
)
from giga_agent.core.integrations.mcp_provider import McpServerProvider
from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

logger = get_logger(__name__)

GITHUB_PROVIDER_KEY = "github"
YANDEX_PROVIDER_KEY = "yandex"
GOOGLE_PROVIDER_KEY = "google"


def _icon(name: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={name}&sz=64"


def static_providers() -> dict[str, IntegrationProvider]:
    """Build the configured static/manual providers, keyed by provider key.

    Providers requiring client credentials are only included when configured.
    """
    settings = get_settings()
    providers: dict[str, IntegrationProvider] = {}

    # GitHub — manually entered Personal Access Token.
    providers[GITHUB_PROVIDER_KEY] = StaticOAuthProvider(
        StaticOAuthConfig(
            key=GITHUB_PROVIDER_KEY,
            label="GitHub",
            icon=_icon("github.com"),
            auth_kind="manual_token",
            validate_url="https://api.github.com/user",
            auth_header_scheme="Bearer",
            manual_fields=[
                ManualField(
                    key="token",
                    label="GitHub Personal Access Token",
                    placeholder="ghp_...",
                )
            ],
        )
    )

    # VK — provider is defined in the VK module; register it here so it is
    # resolvable by the integrations API and the shared token-fetch path.
    from giga_agent.modules.vk.provider import VK_PROVIDER_KEY, build_vk_provider

    providers[VK_PROVIDER_KEY] = build_vk_provider()

    # Google — OAuth (only if app client creds are configured). The provider is
    # defined in the Gmail community module; register it here so it is resolvable
    # by the integrations API and the shared token-fetch path.
    if settings.google_oauth_client_id and settings.google_oauth_client_secret:
        from giga_agent.modules.community.google.gmail.provider import (
            build_google_provider,
        )

        providers[GOOGLE_PROVIDER_KEY] = build_google_provider()

    # Yandex — OAuth (only if app client creds are configured).
    if settings.yandex_oauth_client_id and settings.yandex_oauth_client_secret:
        providers[YANDEX_PROVIDER_KEY] = StaticOAuthProvider(
            StaticOAuthConfig(
                key=YANDEX_PROVIDER_KEY,
                label="Яндекс",
                icon=_icon("yandex.ru"),
                auth_kind="oauth2",
                authorization_endpoint="https://oauth.yandex.ru/authorize",
                token_endpoint="https://oauth.yandex.ru/token",
                client_id=settings.yandex_oauth_client_id,
                client_secret=settings.yandex_oauth_client_secret,
                scope=settings.yandex_oauth_scope,
                validate_url="https://login.yandex.ru/info?format=json",
                auth_header_scheme="OAuth",
            )
        )

    return providers


def get_static_provider(key: str) -> IntegrationProvider | None:
    return static_providers().get(key)


async def get_provider(
    provider_key: str, *, db
) -> IntegrationProvider | None:
    """Resolve a provider by key. ``db`` is needed only for ``mcp:`` keys."""
    if provider_key.startswith("mcp:"):
        from giga_agent.models.mcp_server import McpServerRepository

        try:
            server_id = uuid.UUID(provider_key[len("mcp:"):])
        except ValueError:
            return None
        server = await McpServerRepository(db).get_by_id(server_id)
        return McpServerProvider(server) if server is not None else None

    return get_static_provider(provider_key)


def collect_module_providers(modules) -> list[IntegrationProvider]:
    """Aggregate providers declared by modules, de-duplicated by key.

    Mirrors :func:`giga_agent.core.module.collect_module_secrets`.
    """
    seen: set[str] = set()
    out: list[IntegrationProvider] = []
    for module in modules:
        for provider in module.get_providers():
            if provider.key in seen:
                continue
            seen.add(provider.key)
            out.append(provider)
    return out
