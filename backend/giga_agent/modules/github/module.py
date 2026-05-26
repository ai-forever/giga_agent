from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort

GITHUB_SECRET_KEY = "GITHUB_PERSONAL_ACCESS_TOKEN"


def _has_secret(user: UserShort | None, key: str) -> bool:
    if user is None:
        return False
    raw = getattr(user, "secrets", None)
    if not isinstance(raw, dict):
        return False
    value = raw.get(key)
    if value is None:
        return False
    return bool(str(value).strip())


class GitHubModule(BaseModule):
    id: str = "github"
    label: str = "GitHub"
    description: str = "Работа с репозиториями, issues и pull requests"
    icon: str = "Github"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return _has_secret(user, GITHUB_SECRET_KEY)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": GITHUB_SECRET_KEY,
                "description": "GitHub Personal Access Token для доступа к GitHub API.",
                "type": "pass",
            }
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent
        if not _has_secret(user, GITHUB_SECRET_KEY):
            return []
        from giga_agent.modules.github.tools import (
            get_pull_request,
            get_workflow_runs,
            list_pull_requests,
        )

        return [get_workflow_runs, list_pull_requests, get_pull_request]
