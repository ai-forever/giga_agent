"""Scraper модуль — подключает инструмент чтения страниц по URL."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.scraper.prompts import SCRAPER_MODULE_INSTRUCTIONS
from giga_agent.modules.scraper.tool import get_urls


class ScraperModule(BaseModule):
    id: str = "scraper"

    @staticmethod
    def _is_enabled(user: UserShort | None) -> bool:
        if user is None:
            return False
        return (user.fast_llm_id or user.llm_id) is not None

    async def get_tools(self, user: UserShort | None, agent: BaseAgent) -> List[BaseTool]:
        _ = agent
        if not self._is_enabled(user):
            return []
        return [get_urls]

    async def get_instructions(self, user: UserShort | None, agent: BaseAgent) -> str | None:
        _ = agent
        if not self._is_enabled(user):
            return None
        return SCRAPER_MODULE_INSTRUCTIONS
