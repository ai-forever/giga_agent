"""E2B sandbox-specific tools."""

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
    """Opens a port in the E2B sandbox and returns a public URL for the user.

    Args:
        port: Port number to open
    """
    sandbox_runtime, _, _ = await _resolve_repl_runtime_context(runtime)
    await sandbox_runtime._ensure_e2b_sandbox_connected()
    host = sandbox_runtime._e2b_sandbox.get_host(port)
    url = f"https://{host}"
    return json.dumps(
        {
            "url": url,
            "port": port,
            "hint": "Отдай эту ссылку пользователю, чтобы он мог открыть результат в браузере.",
        },
        ensure_ascii=False,
    )
