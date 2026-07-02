"""MCP-server OAuth provider: dynamic discovery + DCR over the shared store.

Wraps an :class:`McpServer` row. The authorization flow keeps using the
MCP-specific callback URL and cashews namespace (so existing DCR registrations
and the frontend popup keep working — see the migration plan, Variant A).

Call-time token refresh for MCP is handled by the mcp SDK
``OAuthClientProvider`` (see ``oauth_provider.build_oauth_auth``), not by
:meth:`access_token` here.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from mcp.client.auth import PKCEParameters

from giga_agent.core.db import get_session_factory
from giga_agent.models.mcp_server import McpServer
from giga_agent.models.oauth_connection import (
    OAuthConnectionRepository,
    mcp_provider_key,
)
from giga_agent.core.integrations import oauth_flow, state
from giga_agent.core.integrations.base import (
    ConnectionStatus,
    IntegrationProvider,
)
from giga_agent.core.integrations.errors import ReauthRequired
from giga_agent.core.integrations.token_storage import mcp_callback_url

_EXPIRY_LEEWAY_SECONDS = 60


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"****{value[-4:]}" if len(value) > 4 else "****"


def _resolve_scope(
    configured: str | None, scopes_supported: list[str] | None
) -> str | None:
    """Resolve the OAuth scope to request.

    When a scope is explicitly configured, honor it (and append
    ``offline_access`` if the server advertises it, so a refresh token is
    issued). When nothing is configured, fall back to the server's full
    advertised scope set — requesting only ``offline_access`` would drop the
    resource scope (e.g. Arcade's ``mcp``) and tool calls would 403. Without a
    refresh token the connection dies at the first token expiry.
    """
    if configured:
        requested = configured.split()
    elif scopes_supported:
        requested = list(scopes_supported)
    else:
        requested = []
    if scopes_supported and "offline_access" in scopes_supported:
        if "offline_access" not in requested:
            requested.append("offline_access")
    return " ".join(requested) if requested else None


class McpServerProvider(IntegrationProvider):
    auth_kind = "oauth2"

    def __init__(self, server: McpServer) -> None:
        self._server = server
        self.key = mcp_provider_key(server.id)
        self.label = server.name or server.url
        self.icon = None

    async def authorization_url(
        self, *, user_id: uuid.UUID, db, base_url: str
    ) -> str:
        server = self._server
        settings = server.settings or {}
        redirect_uri = mcp_callback_url(base_url)

        info = await oauth_flow.discover_auth_server(server.url)

        scope = _resolve_scope(settings.get("scope"), info.scopes_supported)

        client_id = settings.get("client_id")
        client_secret = settings.get("client_secret")
        if not client_id:
            if not settings.get("use_dcr", True):
                raise ValueError(
                    "No client_id configured and dynamic registration is disabled"
                )
            client_info = await oauth_flow.register_client(
                server_url=server.url,
                registration_endpoint=info.registration_endpoint,
                redirect_uri=redirect_uri,
                scope=scope,
                token_endpoint_auth_methods=info.token_endpoint_auth_methods_supported,
            )
            client_id = client_info.client_id
            client_secret = client_info.client_secret
            # Persist DCR creds so the call-time refresh path can reuse them.
            await OAuthConnectionRepository(db).upsert(
                user_id=user_id,
                provider_key=self.key,
                client_id=client_id,
                client_secret=client_secret,
            )

        pkce = PKCEParameters.generate()
        st = secrets.token_urlsafe(32)
        await state.store_oauth_state(
            namespace=state.MCP_STATE_NS,
            state=st,
            data={
                "user_id": str(user_id),
                "provider_key": self.key,
                "server_url": server.url,
                "code_verifier": pkce.code_verifier,
                "token_endpoint": info.token_endpoint,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "scope": scope,
            },
        )
        return oauth_flow.build_authorization_url(
            authorization_endpoint=info.authorization_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=st,
            code_challenge=pkce.code_challenge,
            scope=scope,
            server_url=server.url,
        )

    async def access_token(self, *, user_id: uuid.UUID) -> str:
        factory = await get_session_factory()
        async with factory() as session:
            row = await OAuthConnectionRepository(session).get(user_id, self.key)
        if row is None or not row.access_token:
            raise ReauthRequired(self.key, "no token stored")
        return row.access_token

    async def status(self, *, user_id: uuid.UUID) -> ConnectionStatus:
        factory = await get_session_factory()
        async with factory() as session:
            row = await OAuthConnectionRepository(session).get(user_id, self.key)
        if row is None or not row.access_token:
            return ConnectionStatus(status="not_connected")
        expired = False
        if row.expires_at is not None:
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc).timestamp()
            expired = expires_at.timestamp() - now <= _EXPIRY_LEEWAY_SECONDS
        if expired and not row.refresh_token:
            return ConnectionStatus(
                status="needs_reauth", token_hint=_mask(row.access_token)
            )
        return ConnectionStatus(
            status="connected",
            scope=row.scope,
            token_hint=_mask(row.access_token),
        )
