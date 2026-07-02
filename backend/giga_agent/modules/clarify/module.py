from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from giga_agent.core.module import BaseModule

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort


class ClarifyModule(BaseModule):
    """Service module that gives the agent an ask_questions tool.

    No ``label`` ⟹ always-on service module invisible in the UI module toggles.
    """

    id: str = "clarify"

    @staticmethod
    def _is_disabled_context(config: RunnableConfig | None) -> bool:
        """Disable ask_questions where there's no interactive user to answer.

        Channel runs (no synchronous UI) and scheduled/background runs (nobody is
        watching) carry these flags in the thread metadata (langgraph surfaces
        them in ``config.metadata``).
        """
        if not isinstance(config, dict):
            return False
        metadata = config.get("metadata") or {}
        return bool(
            metadata.get("is_channel")
            or metadata.get("is_scheduled")
            or metadata.get("type") == "scheduled_task"
        )

    async def _get_tools(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        if self._is_disabled_context(config):
            return []

        from giga_agent.modules.clarify.tools import ask_questions

        return [ask_questions]

    async def get_instructions(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        state: "AgentState | None" = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = user, agent, state, kwargs
        if self._is_disabled_context(config):
            return None

        return (
            "You have the `ask_questions` tool for gathering structured input from the user. "
            "Use it when the request is ambiguous or you need specific clarifications before proceeding. "
            "Important: an 'Other' free-text option is always added automatically to every question in the UI — "
            "do NOT include your own 'Other' / 'Custom' / 'Свой вариант' option in the options list. "
            "Keep option texts short and clear."
        )
