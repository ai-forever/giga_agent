"""Image модуль — подключает tools генерации изображений для активного пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.models.users import UserShort
from giga_agent.modules.image.prompts import IMAGE_MODULE_INSTRUCTIONS


class ImageModule(BaseModule):
    id: str = "image"
    label: str = "Генерация изображений"
    description: str = "Создание изображений по текстовому описанию"
    icon: str = "Image"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return user is not None and user.image_generator_id is not None

    async def _resolve_runtime_cls(
        self,
        user: UserShort | None,
        *,
        config=None,
    ) -> type[BaseImageGenerator] | None:
        _ = user
        if config is None:
            return None

        try:
            from giga_agent.core.agent.runtime_resolver import RuntimeResolver

            resolver = RuntimeResolver.from_config(config)
            if not resolver.has_image_generator:
                return None
            runtime = await resolver.get_image_generator()
            return type(runtime)
        except (ValueError, RuntimeError):
            return None

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs: Any
    ) -> List[BaseTool]:
        _ = agent
        runtime_cls = await self._resolve_runtime_cls(user, config=config)
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
        _ = agent, state, kwargs
        runtime_cls = await self._resolve_runtime_cls(user, config=config)
        if runtime_cls is None:
            return None
        return IMAGE_MODULE_INSTRUCTIONS
