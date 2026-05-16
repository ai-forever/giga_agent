"""Модуль инструментов анализа изображений через текущий LLM пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserShort
from giga_agent.modules.analyze_images.prompts import ANALYZE_IMAGES_MODULE_INSTRUCTIONS
from giga_agent.modules.analyze_images.tool import analyze_image


class AnalyzeImagesModule(BaseModule):
    id: str = "analyze_images"

    async def _is_enabled(self, user: UserShort | None) -> bool:
        if user is None:
            return False

        factory = await get_session_factory()
        async with factory() as session:
            for llm_id in (user.llm_id, user.fast_llm_id):
                if llm_id is None:
                    continue
                try:
                    llm_runtime = await LLMManager.resolve_by_id(
                        llm_id, session=session
                    )
                except Exception:
                    continue
                if llm_runtime.can_analyze_image():
                    return True
        return False

    async def get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
    ) -> List[BaseTool]:
        _ = agent
        if not await self._is_enabled(user):
            return []
        return [analyze_image]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if not await self._is_enabled(user):
            return None
        return ANALYZE_IMAGES_MODULE_INSTRUCTIONS
