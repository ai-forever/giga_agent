from __future__ import annotations

import os
from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.models.users import UserShort
from giga_agent.modules.mock_tracker import data
from giga_agent.modules.tracker_base import BaseTrackerModule


def _enabled() -> bool:
    """Демо-трекер живёт за флагом — чтобы не маячить в обычной работе."""
    return os.getenv("GIGA_AGENT_ENABLE_MOCK_TRACKER", "").lower() in (
        "1",
        "true",
        "yes",
    )


class MockTrackerModule(BaseTrackerModule):
    """Фейковый второй трекер — доказательство расширяемости кита.

    Наследует BaseTrackerModule (тот же контракт и REST переходов, что у Яндекса),
    данные — в памяти. Фронт рендерит его тем же китом БЕЗ единой правки. За
    env-флагом GIGA_AGENT_ENABLE_MOCK_TRACKER.
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

    async def widget_list_transitions(
        self, user: UserShort, issue_key: str
    ) -> list[dict[str, Any]]:
        _ = user
        return data.transitions_for(issue_key)

    async def widget_execute_transition(
        self, user: UserShort, issue_key: str, transition_id: str
    ) -> dict[str, Any] | None:
        _ = user
        return data.apply_transition(issue_key, transition_id)

    async def widget_get_issue(
        self, user: UserShort, issue_key: str
    ) -> dict[str, Any] | None:
        _ = user
        return data.get_issue(issue_key)

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent, config, kwargs
        if not _enabled():
            return []
        from giga_agent.modules.mock_tracker.tools import (
            mock_board,
            mock_get_issue,
            mock_search_issues,
        )

        return [mock_search_issues, mock_get_issue, mock_board]
