"""Local Docker sandbox-specific tools."""

from __future__ import annotations

import json

from langchain.tools import tool, ToolRuntime

from giga_agent.modules.repl.tools import _resolve_repl_runtime_context


@tool(parse_docstring=True, extras={"repl_save": False})
async def open_port(port: int, runtime: ToolRuntime) -> str:
    """Opens a port in the local Docker sandbox and returns a localhost URL for the user.

    Args:
        port: Port number to open
    """
    sandbox_runtime, _, _ = await _resolve_repl_runtime_context(runtime)
    url = await sandbox_runtime.expose_port(port)
    return json.dumps(
        {
            "url": url,
            "port": port,
            "hint": "Отдай эту ссылку пользователю, чтобы он мог открыть результат в браузере.",
        },
        ensure_ascii=False,
    )
