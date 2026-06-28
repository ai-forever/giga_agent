from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, List, Optional

from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.mcp_server import McpServer, McpServerRepository
from giga_agent.modules.mcp.local_config import (
    disabled_local_names,
    load_local_servers,
)
from giga_agent.modules.mcp.resolved import disambiguate_names, resolve_db_server
from giga_agent.modules.mcp.source import McpToolSource

if TYPE_CHECKING:
    from fastapi import APIRouter

    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.connectors.sources import ToolSource
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

    async def get_tool_sources(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        *,
        config=None,
        **kwargs: Any,
    ) -> "List[ToolSource]":
        """Один :class:`McpToolSource` на каждый доступный сервер (DB + local).

        MCP «тулы» — не `BaseTool`, поэтому доставка не через дефолтный
        `lazy_tools`-путь, а через собственный источник.
        """
        _ = agent, config, kwargs
        if user is None:
            return []
        factory = await get_session_factory()
        async with factory() as session:
            db_servers = await McpServerRepository(session).get_readable_for_user(
                user.id, only_active=True
            )
        resolved = [resolve_db_server(s) for s in db_servers]
        disabled = disabled_local_names(user.settings)
        resolved.extend(
            s for s in load_local_servers().values() if s.name not in disabled
        )
        # Same-host servers (the URL-derived fallback name) would otherwise share
        # a connector name; make names unique so the model can address each one.
        disambiguate_names(resolved)
        return [McpToolSource(s) for s in resolved]
