"""VK integration provider (manual API token).

Defined here in the VK module rather than the generic registry; the registry
merely registers it (lazy import) so it is resolvable by the integrations API
and the shared ``service.get_access_token`` path used by VK tools.
"""

from __future__ import annotations

import httpx

from giga_agent.core.logging import get_logger
from giga_agent.core.integrations.base import ManualField
from giga_agent.core.integrations.static_provider import (
    StaticOAuthConfig,
    StaticOAuthProvider,
)

logger = get_logger(__name__)

VK_PROVIDER_KEY = "vk"
VK_API_VERSION = "5.199"


class VKTokenProvider(StaticOAuthProvider):
    """Manual-token VK provider with a real liveness check.

    VK authenticates with an ``access_token`` query param (not a Bearer header),
    so the generic ``validate_url`` probe does not apply — we call ``users.get``
    directly and treat a non-error response as a valid token.
    """

    async def validate(self, token: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.vk.com/method/users.get",
                    params={"access_token": token, "v": VK_API_VERSION},
                )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 — network/parse → treat as invalid
            logger.warning("VK token validation failed: %s", exc)
            return False
        return isinstance(data, dict) and "response" in data


def build_vk_provider() -> VKTokenProvider:
    return VKTokenProvider(
        StaticOAuthConfig(
            key=VK_PROVIDER_KEY,
            label="VK",
            icon="https://www.google.com/s2/favicons?domain=vk.com&sz=64",
            auth_kind="manual_token",
            manual_fields=[
                ManualField(
                    key="token",
                    label="VK API token",
                    placeholder="vk1.a...",
                )
            ],
        )
    )
