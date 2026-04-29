from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.io.prompts import IO_MODULE_INSTRUCTIONS
from giga_agent.modules.io.tools import edit_file, read_file, write_file


class IOModule(BaseModule):
    id: str = "io"

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = user, agent
        return [read_file, write_file, edit_file]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        **kwargs: Any,
    ) -> str | None:
        _ = user, agent, state, kwargs
        return IO_MODULE_INSTRUCTIONS

    def get_api_router(self, **kwargs: Any):
        _ = kwargs
        return None
