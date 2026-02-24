from __future__ import annotations

from typing import List

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.core.agent.types import Collection as StateCollection
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.rag.api import router as rag_api_router
from giga_agent.modules.rag.tools import get_documents, get_rag_info


class RagModule(BaseModule):
    id: str = "rag"

    def get_api_router(self) -> APIRouter:
        return rag_api_router

    async def get_tools(self, user: UserShort | None, agent: BaseAgent) -> List[BaseTool]:
        _ = user, agent
        return [get_documents]

    async def get_instructions(self, user: UserShort | None, agent: BaseAgent) -> str | None:
        _ = agent
        if user is None:
            return None

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
