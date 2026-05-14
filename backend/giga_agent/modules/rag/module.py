from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.conf import get_settings
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.agent.types import Collection as StateCollection
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.rag.api import router as rag_api_router
from giga_agent.modules.rag.tools import get_documents, get_rag_info


def _is_cli() -> bool:
    return get_settings().giga_agent_runtime == "cli"


class RagModule(BaseModule):
    id: str = "rag"

    def get_api_router(self, **kwargs: Any) -> APIRouter | None:
        _ = kwargs
        return rag_api_router

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs: Any
    ) -> List[BaseTool]:
        _ = agent
        if _is_cli():
            return []
        from giga_agent.core.agent.runtime_resolver import RuntimeResolver

        if config is not None:
            resolver = RuntimeResolver.from_config(config)
            if resolver.has_embedding:
                return [get_documents]
            return []
        if user and user.embedding_id:
            return [get_documents]
        return []

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if _is_cli():
            return None
        if user is None:
            return None
        if state is not None:
            return get_rag_info(state.get("collections", []))
        factory = await get_session_factory()
        async with factory() as session:
            rows = await RagCollectionsRepository(session).list_by_owner(user.id)

        collections: list[StateCollection] = [
            {
                "uuid": str(r.id),
                "name": r.name,
                "metadata": (r.metadata_ or {}),  # type: ignore[typeddict-item]
            }
            for r in rows
        ]
        return get_rag_info(collections)
