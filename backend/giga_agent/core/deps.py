"""
Общие FastAPI dependencies для ядра Giga Agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent


def get_agent(request: Request) -> "BaseAgent":
    """
    Получить текущий экземпляр агента из app.state.

    Использование в роутерах:
        from giga_agent.core.deps import get_agent

        @router.get("/example")
        async def example(agent: Annotated[BaseAgent, Depends(get_agent)]):
            ...
    """
    return request.app.state.agent
