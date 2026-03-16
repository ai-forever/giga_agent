from __future__ import annotations

from typing import List

from giga_agent.core.module import BaseModule
from giga_agent.models import UserShort
from langchain_core.tools import BaseTool

from .subgraph import graph, run_example_graph


class WithSubgraphModule(BaseModule):
    id: str = 'with_subgraph'

    def get_subgraphs(self) -> dict[str, str]:
        """Регистрация подграфов модуля"""
        return {
            "example_graph": "agent.with_subgraph.subgraph:graph"
        }
    
    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> List[BaseTool]:
        """Предоставление инструментов модуля"""
        return [run_example_graph]