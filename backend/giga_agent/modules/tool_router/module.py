from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort


class ToolRouterModule(BaseModule):
    # label пустой → сервисный модуль: его тул (request_tools) всегда доступен
    # и не подлежит отключению через disabled_modules.
    id: str = "tool_router"

    def get_middleware(self, **kwargs: Any) -> Optional[AgentMiddleware]:
        _ = kwargs
        from giga_agent.modules.tool_router.middleware import ToolRouterMiddleware

        return ToolRouterMiddleware()

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent, config, kwargs
        from giga_agent.modules.tool_router.tools import request_tools

        return [request_tools]
