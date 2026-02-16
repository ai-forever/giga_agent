"""Image модуль — подключает tools генерации изображений для активного пользователя."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.image.prompts import IMAGE_MODULE_INSTRUCTIONS


class ImageModule(BaseModule):
    id: str = "image"

    @staticmethod
    def _is_enabled(user: UserShort | None) -> bool:
        return user is not None and user.image_generator_id is not None

    async def _resolve_runtime_cls(
        self,
        user: UserShort | None,
    ) -> type[BaseImageGenerator] | None:
        if not self._is_enabled(user):
            return None

        assert user is not None
        assert user.image_generator_id is not None

        record = await ImageGeneratorRepository.get_cached_or_db(
            user.image_generator_id,
            use_cache=True,
        )
        if record is None:
            return None
        if not record.is_active:
            return None
        if record.owner_id != user.id:
            return None

        try:
            return ImageGeneratorRegistry.get(record.type)
        except ValueError:
            return None

    async def get_tools(self, user: UserShort | None, agent: BaseAgent) -> List[BaseTool]:
        _ = agent
        runtime_cls = await self._resolve_runtime_cls(user)
        if runtime_cls is None:
            return []
        return runtime_cls.get_tools()

    async def get_instructions(self, user: UserShort | None, agent: BaseAgent) -> str | None:
        _ = agent
        runtime_cls = await self._resolve_runtime_cls(user)
        if runtime_cls is None:
            return None
        return IMAGE_MODULE_INSTRUCTIONS
