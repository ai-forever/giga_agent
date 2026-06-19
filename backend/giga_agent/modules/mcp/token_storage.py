"""DB-backed :class:`mcp.client.auth.TokenStorage` for per-user MCP tokens.

Each instance is scoped to a ``(user_id, server_id)`` pair and opens its own
short-lived DB sessions, so it is safe to use from the mcp SDK
``OAuthClientProvider`` outside of any request-scoped session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from giga_agent.conf import GIGA_PREFIX_API, get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.models.mcp_server import McpOAuthTokenRepository


def resolve_base_url() -> str | None:
    """Public base URL for OAuth redirects.

    Prefers ``GIGA_AGENT_BASE_URL``; falls back to ``GIGA_AGENT_HOST`` (+ port),
    which the dev server sets (see ``cli/commands/dev.py``).
    """
    settings = get_settings()
    if settings.giga_agent_base_url:
        return settings.giga_agent_base_url
    host = settings.giga_agent_host
    if host:
        base = host.rstrip("/")
        if settings.giga_agent_port:
            base = f"{base}:{settings.giga_agent_port}"
        return base
    return None


def callback_url(base_url: str) -> str:
    return (
        f"{base_url.rstrip('/')}/api{GIGA_PREFIX_API}/mcp/servers/oauth/callback"
    )


class DbTokenStorage(TokenStorage):
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        server_id: uuid.UUID,
        base_url: str,
    ) -> None:
        self._user_id = user_id
        self._server_id = server_id
        self._base_url = base_url

    async def get_tokens(self) -> OAuthToken | None:
        factory = await get_session_factory()
        async with factory() as session:
            row = await McpOAuthTokenRepository(session).get(
                self._user_id, self._server_id
            )
        if row is None or not row.access_token:
            return None
        expires_in: int | None = None
        if row.expires_at is not None:
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            delta = (expires_at - datetime.now(timezone.utc)).total_seconds()
            expires_in = max(0, int(delta))
        return OAuthToken(
            access_token=row.access_token,
            token_type=row.token_type or "Bearer",
            expires_in=expires_in,
            scope=row.scope,
            refresh_token=row.refresh_token,
        )

    async def set_tokens(self, tokens: OAuthToken) -> None:
        expires_at = None
        if tokens.expires_in is not None:
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + tokens.expires_in,
                tz=timezone.utc,
            )
        factory = await get_session_factory()
        async with factory() as session:
            await McpOAuthTokenRepository(session).upsert(
                user_id=self._user_id,
                server_id=self._server_id,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=expires_at,
                token_type=tokens.token_type or "Bearer",
                scope=tokens.scope,
            )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        factory = await get_session_factory()
        async with factory() as session:
            row = await McpOAuthTokenRepository(session).get(
                self._user_id, self._server_id
            )
        if row is None or not row.client_id:
            return None
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=row.client_secret,
            redirect_uris=[callback_url(self._base_url)],
            token_endpoint_auth_method=(
                "client_secret_post" if row.client_secret else "none"
            ),
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        factory = await get_session_factory()
        async with factory() as session:
            await McpOAuthTokenRepository(session).upsert(
                user_id=self._user_id,
                server_id=self._server_id,
                client_id=client_info.client_id,
                client_secret=client_info.client_secret,
            )
