from __future__ import annotations

import os
from typing import Any, List

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.mock_tracker.api import router as mock_api_router


def _enabled() -> bool:
    """Демо-трекер живёт за флагом — чтобы не маячить в обычной работе."""
    return os.getenv("GIGA_AGENT_ENABLE_MOCK_TRACKER", "").lower() in (
        "1",
        "true",
        "yes",
    )


class MockTrackerModule(BaseModule):
    """Фейковый второй трекер — доказательство расширяемости кита.

    Эмитит нормализованный контракт `widget=issue_board`; фронт рендерит его тем
    же китом, что и Яндекс, БЕЗ единой правки. За env-флагом
    GIGA_AGENT_ENABLE_MOCK_TRACKER.
    """

    id: str = "mock_tracker"
    label: str = "Демо-трекер"
    description: str = "Фейковый трекер для проверки provider-agnostic UI"
    icon: str = "Boxes"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = user, config, kwargs
        return _enabled()

    def get_api_router(self, **kwargs: Any) -> APIRouter:
        _ = kwargs
        return mock_api_router

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent, config, kwargs
        if not _enabled():
            return []
        from giga_agent.modules.mock_tracker.tools import (
            mock_get_issue,
            mock_search_issues,
        )

        return [mock_search_issues, mock_get_issue]
