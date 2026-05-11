"""Search модуль — подключает tools интернет-поиска для активного пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.search.prompts import SEARCH_MODULE_INSTRUCTIONS
from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.search_engines.registry import SearchEngineRegistry

# Убедимся, что провайдеры зарегистрированы.
import giga_agent.search_engines  # noqa: F401


class SearchModule(BaseModule):
    id: str = "search"

    @staticmethod
    def _is_enabled(user: UserShort | None) -> bool:
        return user is not None and user.search_engine_id is not None

    async def _resolve_runtime_cls(
        self,
        user: UserShort | None,
    ) -> type[BaseSearchEngine] | None:
        if not self._is_enabled(user):
            return None

        factory = await get_session_factory()
        async with factory() as session:
            record = await SearchEngineRepository.get_cached_or_db(
                user.search_engine_id,
                session=session,
            )
        if record is None:
            return None
        if not record.is_active:
            return None

        try:
            return SearchEngineRegistry.get(record.type)
        except ValueError:
            return None

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs: Any
    ) -> List[BaseTool]:
        _ = agent
        from giga_agent.core.agent.runtime_resolver import RuntimeResolver

        if config is not None:
            resolver = RuntimeResolver.from_config(config)
            if not resolver.has_search_engine:
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
        return SEARCH_MODULE_INSTRUCTIONS
