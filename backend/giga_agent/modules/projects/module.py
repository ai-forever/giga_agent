"""ProjectsModule — exposes Projects CRUD API and injects project instructions."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional

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
from giga_agent.utils.langgraph_sdk import get_client

logger = get_logger(__name__)


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _project_id_from_dict(d: Mapping[str, Any] | None) -> uuid.UUID | None:
    if not isinstance(d, Mapping):
        return None
    return _coerce_uuid(d.get("project_id"))


def _thread_id_from_config(
    config: RunnableConfig | dict[str, Any] | None,
) -> str | None:
    if not isinstance(config, dict):
        return None
    for source in ("metadata", "configurable"):
        section = config.get(source) or {}
        if not isinstance(section, Mapping):
            continue
        thread_id = section.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip().strip("/")
    return None


async def _resolve_project_id(
    config: RunnableConfig | dict[str, Any] | None,
) -> uuid.UUID | None:
    if not isinstance(config, dict):
        return None
    for source in ("metadata", "configurable"):
        section = config.get(source) or {}
        candidate = _project_id_from_dict(section)
        if candidate is not None:
            return candidate

    thread_id = _thread_id_from_config(config)
    if not thread_id:
        return None
    try:
        client = get_client(config)
        thread = await client.threads.get(thread_id)
    except Exception:
        logger.exception(
            "ProjectsModule: failed to fetch thread metadata for %s", thread_id
        )
        return None
    return _project_id_from_dict(thread.get("metadata"))


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

        project_id = await _resolve_project_id(config)
        if project_id is None:
            return None

        try:
            factory = await get_session_factory()
            async with factory() as session:
                repo = ProjectRepository(session)
                project = await repo.get_for_owner(project_id, user.id)
        except Exception:
            logger.exception("ProjectsModule.get_instructions: lookup failed")
            return None

        if project is None or not project.instructions:
            return None

        return PROJECT_INSTRUCTIONS_HEADER.format(
            name=project.name,
            instructions=project.instructions.strip(),
        )
