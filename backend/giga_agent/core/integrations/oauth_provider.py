"""Call-time OAuth2 connection auth backed by the shared connection store.

Builds an mcp SDK ``OAuthClientProvider`` backed by :class:`DbTokenStorage`.
The provider transparently refreshes access tokens using the stored refresh
token. Interactive authorization is NOT performed here — if no token is stored
yet, the caller decides how to surface that (MCP raises
:class:`McpAuthRequiredError`).
"""

from __future__ import annotations

import uuid

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

from giga_agent.core.integrations.token_storage import DbTokenStorage


async def _raise_redirect(_url: str) -> None:
    raise RuntimeError("interactive authorization required")


async def _raise_callback() -> tuple[str, str | None]:
    raise RuntimeError("interactive authorization required")


def build_oauth_client_provider(
    *,
    provider_key: str,
    server_url: str,
    scope: str | None,
    client_secret: str | None,
    redirect_uri: str,
    user_id: uuid.UUID,
) -> OAuthClientProvider:
    """An ``httpx.Auth`` provider that refreshes tokens from the shared store."""
    storage = DbTokenStorage(
        user_id=user_id, provider_key=provider_key, redirect_uri=redirect_uri
    )
    client_metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=scope,
        token_endpoint_auth_method=(
            "client_secret_post" if client_secret else "none"
        ),
    )
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=_raise_redirect,
        callback_handler=_raise_callback,
    )


async def has_stored_token(*, user_id: uuid.UUID, provider_key: str) -> bool:
    storage = DbTokenStorage(
        user_id=user_id, provider_key=provider_key, redirect_uri=""
    )
    return await storage.get_tokens() is not None


async def build_oauth_auth(
    *,
    provider_key: str,
    server_url: str,
    scope: str | None,
    client_secret: str | None,
    redirect_uri: str,
    user_id: uuid.UUID,
) -> tuple[dict[str, str], httpx.Auth | None]:
    """Return ``({}, OAuthClientProvider)`` for an authorized connection.

    Raises :class:`ReauthRequired` if no token is stored yet.
    """
    from giga_agent.core.integrations.errors import ReauthRequired

    if not await has_stored_token(user_id=user_id, provider_key=provider_key):
        raise ReauthRequired(provider_key)

    provider = build_oauth_client_provider(
        provider_key=provider_key,
        server_url=server_url,
        scope=scope,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        user_id=user_id,
    )
    return {}, provider
