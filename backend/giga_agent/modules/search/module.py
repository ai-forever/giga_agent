"""Search модуль — подключает tools интернет-поиска для активного пользователя."""

from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.search.prompts import SEARCH_MODULE_INSTRUCTIONS
from giga_agent.search_engines.base import BaseSearchEngine


class SearchModule(BaseModule):
    id: str = "search"
    label: str = "Поиск"
    description: str = "Поиск информации в интернете"
    icon: str = "Globe"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = kwargs
        if config is not None:
            try:
                from giga_agent.core.agent.runtime_resolver import RuntimeResolver

                return RuntimeResolver.from_config(config).has_search_engine
            except (ValueError, RuntimeError):
                pass
        return user is not None and user.search_engine_id is not None

    async def _resolve_runtime_cls(
        self,
        user: UserShort | None,
        *,
        config=None,
    ) -> type[BaseSearchEngine] | None:
        _ = user
        if config is None:
            return None

        try:
            from giga_agent.core.agent.runtime_resolver import RuntimeResolver

            resolver = RuntimeResolver.from_config(config)
            if not resolver.has_search_engine:
                return None
            runtime = await resolver.get_search_engine()
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
        return SEARCH_MODULE_INSTRUCTIONS
