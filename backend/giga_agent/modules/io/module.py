from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.io.tools import read_file


class IOModule(BaseModule):
    id: str = "io"

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = user, agent
        return [read_file]

    def get_api_router(self, **kwargs: Any):
        _ = kwargs
        return None
