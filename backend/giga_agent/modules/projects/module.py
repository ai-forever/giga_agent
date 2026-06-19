"""ProjectsModule — exposes Projects CRUD API and injects project instructions."""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.core.module import BaseModule
from giga_agent.models.project import Project, ProjectRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.projects.api import router as projects_router
from giga_agent.modules.projects.prompts import PROJECT_INSTRUCTIONS_HEADER
from giga_agent.modules.projects.utils import resolve_project_id

logger = get_logger(__name__)


class ProjectsModule(BaseModule):
    id: str = "projects"

    def get_api_router(self, **kwargs: Any):
        return projects_router

    def get_models(self, **kwargs: Any) -> list[type]:
        return [Project]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if user is None or config is None:
            return None

        project_id = await resolve_project_id(config)
        if project_id is None:
            return None

        try:
            factory = await get_session_factory()
            async with factory() as session:
                project = await ProjectRepository.get_cached_or_db_for_owner(
                    project_id, user.id, session=session
                )
        except Exception:
            logger.exception("ProjectsModule.get_instructions: lookup failed")
            return None

        if project is None or not project.instructions:
            return None

        return PROJECT_INSTRUCTIONS_HEADER.format(
            name=project.name,
            instructions=project.instructions.strip(),
        )
