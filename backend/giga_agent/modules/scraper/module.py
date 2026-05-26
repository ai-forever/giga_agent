"""Scraper модуль — подключает инструмент чтения страниц по URL."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.conf import get_settings
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.scraper.prompts import SCRAPER_MODULE_INSTRUCTIONS
from giga_agent.modules.scraper.tool import get_urls


class ScraperModule(BaseModule):
    id: str = "scraper"
    label: str = "Веб-скрапер"
    description: str = "Извлечение данных с веб-страниц по URL"
    icon: str = "Globe2"

    @staticmethod
    def _is_enabled(user: UserShort | None, *, config=None) -> bool:
        if get_settings().giga_agent_scraper_disabled:
            return False
        if config is not None:
            from giga_agent.core.agent.runtime_resolver import RuntimeResolver

            resolver = RuntimeResolver.from_config(config)
            return resolver.has_fast_llm
        if user is None:
            return False
        return (user.fast_llm_id or user.llm_id) is not None

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs: Any
    ) -> List[BaseTool]:
        _ = agent
        if not self._is_enabled(user, config=config):
            return []
        return [get_urls]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if not self._is_enabled(user, config=config):
            return None
        return SCRAPER_MODULE_INSTRUCTIONS
