from typing import Optional

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.module import BaseModule
from giga_agent.middlewares.tool_result import ToolResultMiddleware


class ToolCallInterruptMiddleware(ToolResultMiddleware):
    """Backward-compatible alias for old middleware name."""


class ToolCallInterruptModule(BaseModule):
    id: str = "tool_call_interrupt"

    def get_middleware(self) -> Optional["AgentMiddleware"]:
        return ToolResultMiddleware()
