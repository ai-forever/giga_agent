from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort

VK_SECRET_KEY = "VK_TOKEN"


def _has_secret(user: UserShort | None, key: str) -> bool:
    if user is None:
        return False
    raw = getattr(user, "secrets", None)
    if not isinstance(raw, dict):
        return False
    value = raw.get(key)
    if value is None:
        return False
    return bool(str(value).strip())


class VKModule(BaseModule):
    id: str = "vk"
    label: str = "VK"
    description: str = "Работа с API ВКонтакте"
    icon: str = "MessageCircle"
    lazy_tools: bool = True

    def get_providers(self, **kwargs: Any):
        _ = kwargs
        from giga_agent.modules.vk.provider import build_vk_provider

        return [build_vk_provider()]

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if user is None:
            return False
        # Connected via the integrations store, or a legacy user.secrets token.
        if _has_secret(user, VK_SECRET_KEY):
            return True
        return await self.providers_connected(user)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        # Kept for backward compatibility: existing users may still hold the
        # token in user.secrets. New connections go through the integrations panel.
        _ = kwargs
        return [
            {
                "name": VK_SECRET_KEY,
                "description": "Токен VK API для чтения постов и комментариев.",
                "type": "pass",
            }
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent
        if not _has_secret(user, VK_SECRET_KEY):
            return []
        from giga_agent.modules.vk.tools import (
            vk_get_comments,
            vk_get_last_comments,
            vk_get_posts,
        )

        return [vk_get_posts, vk_get_comments, vk_get_last_comments]
