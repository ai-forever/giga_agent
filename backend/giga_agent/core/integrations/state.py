"""Short-lived OAuth authorization state (cashews) + token finalization.

The authorization-code flow needs to carry per-attempt data (PKCE verifier,
token endpoint, client creds, redirect_uri, the target ``provider_key``) between
``/oauth/start`` and the callback. We stash it in cashews keyed by the opaque
``state`` value, with a short TTL, and consume it once.

Two namespaces share the same format:
- ``mcp:oauth:state`` — MCP servers (kept for the existing MCP callback route).
- ``integrations:oauth:state`` — native (static) providers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from cashews import cache

from giga_agent.core.integrations import oauth_flow

MCP_STATE_NS = "mcp:oauth:state"
INTEGRATIONS_STATE_NS = "integrations:oauth:state"
STATE_TTL = "10m"


def _state_key(namespace: str, state: str) -> str:
    return f"{namespace}:{state}"


async def store_oauth_state(
    *, namespace: str, state: str, data: dict[str, Any]
) -> None:
    await cache.set(_state_key(namespace, state), data, expire=STATE_TTL)


async def pop_oauth_state(
    *, namespace: str, state: str
) -> dict[str, Any] | None:
    """Return the state payload and delete it (one-time use)."""
    key = _state_key(namespace, state)
    data = await cache.get(key)
    if data is None:
        return None
    await cache.delete(key)
    return data


async def finalize_oauth(db, data: dict[str, Any], code: str) -> uuid.UUID:
    """Exchange ``code`` for tokens and upsert into the connection store.

    ``data`` is the payload stored by a provider's ``authorization_url``.
    Returns the ``user_id`` whose connection was written.
    """
    from giga_agent.models.oauth_connection import OAuthConnectionRepository

    token = await oauth_flow.exchange_code(
        token_endpoint=data["token_endpoint"],
        code=code,
        code_verifier=data["code_verifier"],
        redirect_uri=data["redirect_uri"],
        client_id=data["client_id"],
        client_secret=data.get("client_secret"),
        server_url=data.get("server_url"),
    )

    expires_at = None
    if token.expires_in is not None:
        expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + token.expires_in,
            tz=timezone.utc,
        )

    user_id = uuid.UUID(data["user_id"])
    await OAuthConnectionRepository(db).upsert(
        user_id=user_id,
        provider_key=data["provider_key"],
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=expires_at,
        token_type=token.token_type or "Bearer",
        scope=token.scope or data.get("scope"),
        client_id=data["client_id"],
        client_secret=data.get("client_secret"),
    )
    return user_id
