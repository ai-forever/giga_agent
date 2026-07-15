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
from giga_agent.models.project import ProjectRepository
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.projects.utils import resolve_project_id
from giga_agent.modules.rag.api import router as rag_api_router
from giga_agent.modules.rag.tools import get_documents, get_rag_info


def _is_cli() -> bool:
    return get_settings().giga_agent_runtime == "cli"


class RagModule(BaseModule):
    id: str = "rag"
    label: str = "Документы (RAG)"
    description: str = "Поиск и извлечение информации из загруженных документов"
    icon: str = "Files"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return user is not None and user.embedding_id is not None

    def get_api_router(self, **kwargs: Any) -> APIRouter | None:
        _ = kwargs
        return rag_api_router

    async def _get_tools(
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
        _ = agent, kwargs
        if _is_cli():
            return None
        if user is None:
            return None
        if state is not None:
            collections = list(state.get("collections", []))
        else:
            factory = await get_session_factory()
            async with factory() as session:
                rows = await RagCollectionsRepository(session).list_by_owner(user.id)
            collections = [
                {
                    "uuid": str(r.id),
                    "name": r.name,
                    "metadata": (r.metadata_ or {}),  # type: ignore[typeddict-item]
                }
                for r in rows
            ]

        await self._merge_project_collection(collections, user, config)
        return get_rag_info(collections)

    @staticmethod
    async def _merge_project_collection(
        collections: list[StateCollection],
        user: UserShort,
        config: Any,
    ) -> None:
        """Surface a project's backing RAG collection to the agent.

        Project collections are filtered out of the user's "active
        collections" toggle in chat UI, so they never reach state on
        their own. When the current chat belongs to a project, append
        the project's collection to the list shown to the agent.
        """
        if config is None:
            return
        try:
            project_id = await resolve_project_id(config)
        except Exception:
            return
        if project_id is None:
            return

        existing_uuids = {c.get("uuid") for c in collections}
        factory = await get_session_factory()
        async with factory() as session:
            project = await ProjectRepository(session).get_for_owner(
                project_id, user.id
            )
            if project is None or project.collection_id is None:
                return
            collection_uuid = str(project.collection_id)
            if collection_uuid in existing_uuids:
                return
            row = await RagCollectionsRepository(session).get_by_id(
                owner_id=user.id, collection_id=project.collection_id
            )
            if row is None:
                return
            collections.append(
                {
                    "uuid": collection_uuid,
                    "name": row.name,
                    "metadata": (row.metadata_ or {}),  # type: ignore[typeddict-item]
                }
            )
