"""DB-backed :class:`mcp.client.auth.TokenStorage` for per-user connections.

Each instance is scoped to a ``(user_id, provider_key)`` pair and opens its own
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
from giga_agent.models.oauth_connection import OAuthConnectionRepository


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


def mcp_callback_url(base_url: str) -> str:
    """Backend OAuth callback for MCP servers.

    Kept stable: this exact URL is registered with providers during DCR, so
    existing connections would break if it changed.
    """
    return f"{base_url.rstrip('/')}/api{GIGA_PREFIX_API}/mcp/servers/oauth/callback"


def integrations_callback_url(base_url: str) -> str:
    """Backend OAuth callback for native (static) integration providers."""
    return f"{base_url.rstrip('/')}/api{GIGA_PREFIX_API}/integrations/oauth/callback"


class DbTokenStorage(TokenStorage):
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        provider_key: str,
        redirect_uri: str,
    ) -> None:
        self._user_id = user_id
        self._provider_key = provider_key
        self._redirect_uri = redirect_uri

    async def get_tokens(self) -> OAuthToken | None:
        factory = await get_session_factory()
        async with factory() as session:
            row = await OAuthConnectionRepository(session).get(
                self._user_id, self._provider_key
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
            await OAuthConnectionRepository(session).upsert(
                user_id=self._user_id,
                provider_key=self._provider_key,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=expires_at,
                token_type=tokens.token_type or "Bearer",
                scope=tokens.scope,
            )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        factory = await get_session_factory()
        async with factory() as session:
            row = await OAuthConnectionRepository(session).get(
                self._user_id, self._provider_key
            )
        if row is None or not row.client_id:
            return None
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=row.client_secret,
            redirect_uris=[self._redirect_uri],
            token_endpoint_auth_method=(
                "client_secret_post" if row.client_secret else "none"
            ),
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        factory = await get_session_factory()
        async with factory() as session:
            await OAuthConnectionRepository(session).upsert(
                user_id=self._user_id,
                provider_key=self._provider_key,
                client_id=client_info.client_id,
                client_secret=client_info.client_secret,
            )
