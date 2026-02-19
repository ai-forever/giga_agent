from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.vk.tools import (
    vk_get_comments,
    vk_get_last_comments,
    vk_get_posts,
    VK_SECRET_KEY,
)


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

    def get_secrets(self) -> list[SecretMetadata]:
        return [
            {
                "name": VK_SECRET_KEY,
                "description": "Токен VK API для чтения постов и комментариев.",
                "type": "pass",
            }
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = agent
        if not _has_secret(user, VK_SECRET_KEY):
            return []
        return [vk_get_posts, vk_get_comments, vk_get_last_comments]
