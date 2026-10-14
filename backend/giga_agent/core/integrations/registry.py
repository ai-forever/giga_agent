"""Provider registry: resolves a ``provider_key`` to an :class:`IntegrationProvider`.

Three sources, merged by :func:`static_providers`:
- Providers declared by the loaded agent's modules via ``module.get_providers()``
  (VK, Yandex Диск/Трекер/Почта/Календарь, ...). Each module owns its own
  ``*_configured()`` gating, so unconfigured providers are simply absent.
- A small set of *base* providers not owned by any module — standalone
  manual-token integrations like the GitHub PAT (see :func:`_base_providers`).
- MCP servers, resolved dynamically from the DB by ``mcp:<server_id>`` keys.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.module import BaseModule

logger = get_logger(__name__)

GITHUB_PROVIDER_KEY = "github"

# Process-global handle to the loaded agent, set once at construction time
# (see ``BaseAgent.model_post_init``). Lets request-free call sites — the shared
# token-fetch path in ``service.py``, tool execution in ``vk/tools.py`` — resolve
# providers by walking the agent's modules.
_current_agent: "BaseAgent | None" = None


def set_current_agent(agent: "BaseAgent") -> None:
    """Register the loaded agent so ``static_providers`` can enumerate modules."""
    global _current_agent
    _current_agent = agent


def get_current_agent() -> "BaseAgent | None":
    return _current_agent


def _current_modules() -> "tuple[BaseModule, ...]":
    if _current_agent is None:
        return ()
    return tuple(_current_agent.all_modules)


def _icon(name: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={name}&sz=64"


def _base_providers() -> dict[str, IntegrationProvider]:
    """Providers not owned by any agent module (standalone integrations)."""
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

    return providers


def static_providers() -> dict[str, IntegrationProvider]:
    """Build the available static/manual providers, keyed by provider key.

    Providers are collected from the loaded agent's modules (each module gates
    its own availability), then merged with the base providers. Providers
    requiring client credentials are only present when their module reports them
    as configured.
    """
    providers = _base_providers()
    for provider in collect_module_providers(_current_modules()):
        providers[provider.key] = provider
    return providers


def get_static_provider(key: str) -> IntegrationProvider | None:
    return static_providers().get(key)


async def get_provider(provider_key: str, *, db) -> IntegrationProvider | None:
    """Resolve a provider by key. ``db`` is needed only for ``mcp:`` keys."""
    if provider_key.startswith("mcp:"):
        from giga_agent.models.mcp_server import McpServerRepository

        try:
            server_id = uuid.UUID(provider_key[len("mcp:") :])
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
