"""Search модуль — подключает tools интернет-поиска для активного пользователя."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.search.prompts import SEARCH_MODULE_INSTRUCTIONS
from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.search_engines.registry import SearchEngineRegistry

# Убедимся, что провайдеры зарегистрированы.
import giga_agent.search_engines  # noqa: F401


class SubAgentLegacyModule(BaseModule):
    id: str = "subagents_legacy"

    def get_secrets(self) -> list[SecretMetadata]:
        return [
            {
                "name": "TWOGIS_TOKEN",
                "description": "Токен от 2гис (с доступом к поиску и отображению карт)",
            },
            {"name": "SALUTE_SPEECH", "description": "Токен SaluteSpeech"},
            {"name": "SALUTE_SCOPE", "description": "Scope токена SaluteSpeech"},
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        return []

    async def get_instructions(
        self, user: UserShort | None, agent: BaseAgent
    ) -> str | None:
        return ""
