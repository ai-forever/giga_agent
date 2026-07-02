"""Single entry points used by both the MCP client and native module tools."""

from __future__ import annotations

import uuid

from giga_agent.core.db import get_session_factory
from giga_agent.core.integrations.base import ConnectionStatus
from giga_agent.core.integrations.errors import ReauthRequired
from giga_agent.core.integrations.registry import get_provider


async def get_access_token(user_id: uuid.UUID, provider_key: str) -> str:
    """Return a fresh access token for ``(user, provider)``.

    Refreshes transparently. Raises :class:`ReauthRequired` if no usable token
    can be produced (not connected / refresh rejected).
    """
    factory = await get_session_factory()
    async with factory() as session:
        provider = await get_provider(provider_key, db=session)
        if provider is None:
            raise ReauthRequired(provider_key, "unknown provider")
        return await provider.access_token(user_id=user_id)


async def provider_status(
    user_id: uuid.UUID, provider_key: str
) -> ConnectionStatus:
    factory = await get_session_factory()
    async with factory() as session:
        provider = await get_provider(provider_key, db=session)
        if provider is None:
            return ConnectionStatus(status="not_connected", detail="unknown provider")
        return await provider.status(user_id=user_id)


async def is_connected(user_id: uuid.UUID, provider_key: str) -> bool:
    status = await provider_status(user_id, provider_key)
    return status.status == "connected"


async def all_providers_connected(
    user_id: uuid.UUID, provider_keys: list[str]
) -> bool:
    for key in provider_keys:
        if not await is_connected(user_id, key):
            return False
    return True
