"""Auth resolution for backend MCP connections.

Returns the headers and/or an ``httpx.Auth`` to attach to the streamable-HTTP
client for a given server and user.

- ``none``   → no auth.
- ``bearer`` → a static header (default ``Authorization: Bearer <token>``).
- ``oauth2`` → per-user OAuth2 (authorization-code + DCR). Filled in Phase 5;
  until a token is stored, raises :class:`McpAuthRequiredError`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx

from giga_agent.modules.mcp.errors import McpAuthRequiredError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giga_agent.models.mcp_server import McpServer


def _bearer_headers(server: "McpServer") -> dict[str, str]:
    settings = server.settings or {}
    token = settings.get("token")
    if not token:
        raise McpAuthRequiredError(
            f"server '{server.name or server.url}' has no bearer token configured"
        )
    header_name = settings.get("header_name") or "Authorization"
    scheme = settings.get("scheme", "Bearer")
    value = f"{scheme} {token}".strip() if scheme else token
    return {header_name: value}


async def build_connection_auth(
    server: "McpServer",
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None",
) -> tuple[dict[str, str], httpx.Auth | None]:
    """Return ``(headers, httpx_auth)`` for connecting to *server* as *user_id*."""
    auth_type = (server.auth_type or "none").lower()

    if auth_type == "none":
        return {}, None

    if auth_type == "bearer":
        return _bearer_headers(server), None

    if auth_type == "oauth2":
        # Phase 5 wires OAuthClientProvider + DbTokenStorage here. Until then,
        # signal that interactive authorization is required.
        from giga_agent.modules.mcp.oauth_provider import build_oauth_auth

        return await build_oauth_auth(server, user_id=user_id, db=db)

    raise McpAuthRequiredError(f"unsupported auth_type '{auth_type}'")
