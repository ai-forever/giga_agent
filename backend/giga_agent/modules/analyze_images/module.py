"""Модуль инструментов анализа изображений через текущий LLM пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.analyze_images.prompts import ANALYZE_IMAGES_MODULE_INSTRUCTIONS
from giga_agent.modules.analyze_images.tool import (
    analyze_image,
    resolve_image_analyzer_llm,
)


class AnalyzeImagesModule(BaseModule):
    id: str = "analyze_images"
    label: str = "Анализ изображений"
    description: str = "Распознавание и описание содержимого изображений"
    icon: str = "ScanSearch"

    async def _is_enabled(self, user: UserShort | None, *, config=None) -> bool:
        from giga_agent.core.agent.runtime_resolver import RuntimeResolver

        if config is None:
            return False

        try:
            resolver = RuntimeResolver.from_config(config)
            return await resolve_image_analyzer_llm(resolver) is not None
        except Exception:
            return False

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config=None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        _ = agent
        if not await self._is_enabled(user, config=config):
            return []
        return [analyze_image]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if not await self._is_enabled(user, config=config):
            return None
        return ANALYZE_IMAGES_MODULE_INSTRUCTIONS
