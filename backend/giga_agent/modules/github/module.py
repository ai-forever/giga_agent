from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.github.tools import (
    get_pull_request,
    get_workflow_runs,
    list_pull_requests,
    GITHUB_SECRET_KEY,
)


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

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": GITHUB_SECRET_KEY,
                "description": "GitHub Personal Access Token для доступа к GitHub API.",
                "type": "pass",
            }
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = agent
        if not _has_secret(user, GITHUB_SECRET_KEY):
            return []
        return [get_workflow_runs, list_pull_requests, get_pull_request]
