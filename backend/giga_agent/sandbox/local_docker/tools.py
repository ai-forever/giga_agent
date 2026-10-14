"""Local Docker sandbox-specific tools."""

from __future__ import annotations

import json

from langchain.tools import tool, ToolRuntime

from giga_agent.core.agent.tool_policy import (
    ToolConfirmation,
    ToolEffect,
    tool_extras,
)
from giga_agent.modules.repl.tools import _resolve_repl_runtime_context


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.CONDITIONAL,
        repl_save=False,
    ),
)
async def open_port(port: int, runtime: ToolRuntime) -> str:
    """Opens a port in the local Docker sandbox and returns a URL the user can open in a browser. The access scope of the URL (private vs public) depends on the deployment — follow the sandbox runtime instructions in the system prompt.

    Args:
        port: Port number to open
    """
    sandbox_runtime, _, _ = await _resolve_repl_runtime_context(runtime)
    url = await sandbox_runtime.expose_port(port)
    return json.dumps(
        {
            "url": url,
            "port": port,
            "hint": "Отдай эту ссылку пользователю РОВНО как есть, чтобы он открыл результат в браузере. Не дописывай query-параметры (`?__sbx=...`) — токен доступа при необходимости подставляется автоматически.",
        },
        ensure_ascii=False,
    )
