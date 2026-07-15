"""MCP implementation of the core :class:`ToolSource` protocol.

Wraps a single resolved MCP server so the connector meta-tools can list and call
its tools alongside native lazy modules. Reuses the existing MCP client
(``list_server_tools`` / ``call_server_tool``), content processing
(``process_mcp_content``) and the MCP Apps widget metadata helpers.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain.tools import ToolRuntime

from giga_agent.core.agent.connectors.sources import ToolCallOutcome, ToolSpec
from giga_agent.middlewares.tool_result import process_mcp_content
from giga_agent.modules.mcp.client import call_server_tool, list_server_tools
from giga_agent.modules.mcp.errors import McpError
from giga_agent.modules.mcp.resolved import ResolvedServer
from giga_agent.modules.mcp.tools import (
    _error_text,
    _server_icon_url,
    _ui_resource_uri,
    _visible_to_model,
)


class McpToolSource:
    """A :class:`ToolSource` backed by one resolved MCP server."""

    def __init__(self, server: ResolvedServer) -> None:
        self._server = server
        self.name = server.name
        self.label = server.name
        self.icon = _server_icon_url(server)

    async def list_tools(self, *, user_id: uuid.UUID) -> list[ToolSpec]:
        tools = await list_server_tools(self._server, user_id=user_id)
        return [
            ToolSpec.from_schema(
                name=t.get("name"),
                description=t.get("description") or "",
                schema=t.get("inputSchema") or {},
            )
            for t in tools
            if _visible_to_model(t)
        ]

    async def call_tool(
        self,
        tool: str,
        params: dict[str, Any],
        runtime: ToolRuntime,
        *,
        user_id: uuid.UUID,
    ) -> ToolCallOutcome:
        try:
            catalog = await list_server_tools(self._server, user_id=user_id)
        except McpError as exc:
            return ToolCallOutcome(
                content=_error_text(self._server, exc), is_error=True
            )

        try:
            parts, is_error, structured = await call_server_tool(
                self._server, tool, params, user_id=user_id
            )
        except McpError as exc:
            return ToolCallOutcome(
                content=_error_text(self._server, exc), is_error=True
            )

        data, attachments, message = await process_mcp_content(parts, runtime.config)

        if is_error:
            text = (
                data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            )
            return ToolCallOutcome(content=text, is_error=True)

        # MCP Apps: a tool with ``meta.ui.resourceUri`` instantiates an
        # interactive widget. Carry everything the frontend host bridge needs to
        # render it — the widget draws from the call *arguments* and uses
        # ``structuredContent`` for follow-up edits.
        called = next((t for t in catalog if t.get("name") == tool), None)
        resource_uri = _ui_resource_uri(called) if called else None
        extra_attachment: dict[str, Any] | None = None
        if resource_uri:
            extra_attachment = {
                "file_type": "mcp_ui",
                "resource_uri": resource_uri,
                "server": self._server.name,
                "server_id": self._server.cache_id,
                "icon": self.icon,
                "tool": tool,
                "tool_args": params,
                "structured_content": structured,
            }

        payload: dict[str, Any] = {"result": data}
        if message:
            payload["attachments"] = message

        return ToolCallOutcome(
            content=payload,
            attachments=list(attachments),
            is_error=False,
            extra_attachment=extra_attachment,
        )
