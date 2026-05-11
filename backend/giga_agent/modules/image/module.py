"""Image модуль — подключает tools генерации изображений для активного пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
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

        factory = await get_session_factory()
        async with factory() as session:
            record = await ImageGeneratorRepository.get_cached_or_db(
                user.image_generator_id,
                session=session,
            )
        if record is None:
            return None
        if not record.is_active:
            return None

        try:
            return ImageGeneratorRegistry.get(record.type)
        except ValueError:
            return None

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs: Any
    ) -> List[BaseTool]:
        _ = agent
        from giga_agent.core.agent.runtime_resolver import RuntimeResolver

        if config is not None:
            resolver = RuntimeResolver.from_config(config)
            if not resolver.has_image_generator:
                return []
        runtime_cls = await self._resolve_runtime_cls(user)
        if runtime_cls is None:
            return []
        return runtime_cls.get_tools()

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, config, kwargs
        runtime_cls = await self._resolve_runtime_cls(user)
        if runtime_cls is None:
            return None
        return IMAGE_MODULE_INSTRUCTIONS
