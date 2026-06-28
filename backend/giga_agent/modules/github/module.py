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

    def get_providers(self, **kwargs: Any):
        _ = kwargs
        from giga_agent.core.integrations.registry import (
            GITHUB_PROVIDER_KEY,
            get_static_provider,
        )

        provider = get_static_provider(GITHUB_PROVIDER_KEY)
        return [provider] if provider is not None else []

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if user is None:
            return False
        # Connected via the integrations store, or a legacy user.secrets PAT.
        if _has_secret(user, GITHUB_SECRET_KEY):
            return True
        return await self.providers_connected(user)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        # Kept for backward compatibility: existing users may still hold the PAT
        # in user.secrets. New connections go through the integrations panel.
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
        if not await self.is_enabled(user):
            return []
        from giga_agent.modules.github.tools import (
            get_pull_request,
            get_workflow_runs,
            list_pull_requests,
        )

        return [get_workflow_runs, list_pull_requests, get_pull_request]
