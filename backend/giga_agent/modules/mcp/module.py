from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.mcp_server import McpServer, McpServerRepository
from giga_agent.modules.mcp.local_config import load_local_servers
from giga_agent.modules.mcp.tools import mcp_call_tool, mcp_get_info

if TYPE_CHECKING:
    from fastapi import APIRouter

    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort


async def _active_servers(user_id: uuid.UUID) -> list[McpServer]:
    factory = await get_session_factory()
    async with factory() as session:
        return await McpServerRepository(session).get_readable_for_user(
            user_id, only_active=True
        )


class McpModule(BaseModule):
    id: str = "mcp"
    label: str = "MCP"
    description: str = "Подключение внешних MCP-серверов и вызов их инструментов"
    icon: str = "Plug"

    def get_models(self, **kwargs: Any) -> list[type]:
        return [McpServer]

    def get_api_router(self, **kwargs: Any) -> Optional["APIRouter"]:
        _ = kwargs
        from giga_agent.modules.mcp.api import router as mcp_router

        return mcp_router

    async def is_enabled(
        self, user: "UserShort | None", *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if user is None:
            return False
        return len(await _active_servers(user.id)) > 0

    async def _get_tools(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        *,
        config=None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if user is None:
            return []
        if not await _active_servers(user.id):
            return []
        return [mcp_get_info, mcp_call_tool]

    async def get_instructions(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, config, kwargs
        if user is None:
            return None
        lines = []
        for server in await _active_servers(user.id):
            label = server.name or str(server.id)
            lines.append(f"- {label} ({server.url})" if server.url else f"- {label}")
        for local in load_local_servers().values():
            target = local.url or local.command or ""
            lines.append(f"- {local.name} (local, {target})" if target else f"- {local.name} (local)")
        if not lines:
            return None
        listing = "\n".join(lines)
        return (
            "Доступные MCP-серверы:\n"
            f"{listing}\n"
            "Чтобы узнать инструменты сервера, вызови mcp_get_info('<имя сервера>'). "
            "Затем вызывай инструмент через mcp_call_tool('<имя сервера>', '<инструмент>', params='<JSON>')."
        )
