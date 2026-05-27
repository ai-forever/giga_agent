"""ProjectsModule — exposes Projects CRUD API."""

from __future__ import annotations

from typing import Any

from giga_agent.core.module import BaseModule
from giga_agent.models.project import Project
from giga_agent.modules.projects.api import router as projects_router


class ProjectsModule(BaseModule):
    id: str = "projects"

    def get_api_router(self, **kwargs: Any):
        return projects_router

    def get_models(self, **kwargs: Any) -> list[type]:
        return [Project]
