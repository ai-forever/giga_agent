"""Call-time OAuth2 connection auth for MCP servers.

Builds an mcp SDK ``OAuthClientProvider`` backed by :class:`DbTokenStorage`.
The provider transparently refreshes access tokens using the stored refresh
token. Interactive authorization is NOT performed here — if no token is stored
yet, we raise :class:`McpAuthRequiredError` (the user must complete the flow via
the OAuth routes). The redirect/callback handlers therefore just raise.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

from giga_agent.modules.mcp.errors import McpAuthRequiredError
from giga_agent.modules.mcp.token_storage import (
    DbTokenStorage,
    callback_url,
    resolve_base_url,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giga_agent.models.mcp_server import McpServer


async def _raise_redirect(_url: str) -> None:
    raise McpAuthRequiredError("interactive authorization required")


async def _raise_callback() -> tuple[str, str | None]:
    raise McpAuthRequiredError("interactive authorization required")


async def build_oauth_auth(
    server: "McpServer",
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None",
) -> tuple[dict[str, str], httpx.Auth | None]:
    _ = db
    base_url = resolve_base_url()
    if not base_url:
        raise McpAuthRequiredError(
            "OAuth is not configured on the server (set GIGA_AGENT_BASE_URL)"
        )

    storage = DbTokenStorage(
        user_id=user_id, server_id=server.id, base_url=base_url
    )
    if await storage.get_tokens() is None:
        raise McpAuthRequiredError(
            f"server '{server.name or server.url}' requires authorization"
        )

    settings = server.settings or {}
    client_metadata = OAuthClientMetadata(
        redirect_uris=[callback_url(base_url)],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=settings.get("scope"),
        token_endpoint_auth_method=(
            "client_secret_post" if settings.get("client_secret") else "none"
        ),
    )
    provider = OAuthClientProvider(
        server_url=server.url,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=_raise_redirect,
        callback_handler=_raise_callback,
    )
    return {}, provider
