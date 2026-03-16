from __future__ import annotations

from typing import List

from giga_agent.core.module import BaseModule
from giga_agent.models import UserShort
from langchain_core.tools import BaseTool

from agent.with_tool.tools import read_file, list_files


class WithToolModule(BaseModule):
    id: str = "with_tool"

    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> List[BaseTool]:
        return [read_file, list_files]