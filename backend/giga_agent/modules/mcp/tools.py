"""Agent-facing MCP meta-tools: ``mcp_get_info`` and ``mcp_call_tool``.

Only these two static tools are bound to the LLM (decision #1/#2). The set of
servers is surfaced in the system prompt (see ``module.get_instructions``); the
per-server tool detail is fetched here at runtime. Output and errors are tuned
for weak models — flat ``required`` lists, a concrete ``params_example`` per tool,
and explicit next-action error hints.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage

from giga_agent.core.agent.tool_results import build_error_tool_message
from giga_agent.core.db import get_session_factory
from giga_agent.middlewares.tool_result import process_mcp_content
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.modules.mcp.client import call_server_tool, list_server_tools
from giga_agent.modules.mcp.errors import (
    McpAuthRequiredError,
    McpError,
    McpLocalBlockedError,
    McpTimeoutError,
    McpUnreachableError,
)
from giga_agent.modules.mcp.local_config import load_local_servers
from giga_agent.modules.mcp.resolved import ResolvedServer, resolve_db_server
from giga_agent.utils.langgraph_sdk import get_user_id_from_config


def _owner_id(runtime: ToolRuntime) -> uuid.UUID:
    user_id = get_user_id_from_config(runtime.config)
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


async def _all_servers(user_id: uuid.UUID) -> list[ResolvedServer]:
    """Merge DB-backed servers with local file servers (local runtime only)."""
    factory = await get_session_factory()
    async with factory() as session:
        db_servers = await McpServerRepository(session).get_readable_for_user(
            user_id, only_active=True
        )
        resolved = [resolve_db_server(s) for s in db_servers]
    resolved.extend(load_local_servers().values())
    return resolved


def _server_label(server: ResolvedServer) -> str:
    return server.name


def _match_server(servers: list[ResolvedServer], ref: str) -> ResolvedServer | None:
    ref_norm = (ref or "").strip().lower()
    for server in servers:
        if server.name.strip().lower() == ref_norm:
            return server
    for server in servers:
        if server.cache_id.lower() == ref_norm:
            return server
    return None


def _example_for_prop(prop: dict[str, Any]) -> Any:
    if not isinstance(prop, dict):
        return None
    if "enum" in prop and isinstance(prop["enum"], list) and prop["enum"]:
        return prop["enum"][0]
    if "default" in prop:
        return prop["default"]
    prop_type = prop.get("type")
    if isinstance(prop_type, list):
        prop_type = next((t for t in prop_type if t != "null"), None)
    if prop_type == "string":
        return "example"
    if prop_type == "integer":
        return 1
    if prop_type == "number":
        return 1
    if prop_type == "boolean":
        return True
    if prop_type == "array":
        items = prop.get("items") if isinstance(prop.get("items"), dict) else {}
        return [_example_for_prop(items)] if items else []
    if prop_type == "object":
        return {}
    return None


def _build_args_example(schema: dict[str, Any], required: list[str]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    keys = required or list(properties.keys())
    return {key: _example_for_prop(properties.get(key, {})) for key in keys}


def _describe_tool(tool_info: dict[str, Any]) -> dict[str, Any]:
    schema = tool_info.get("inputSchema") or {}
    required = schema.get("required") if isinstance(schema, dict) else None
    required = [str(r) for r in required] if isinstance(required, list) else []
    description = (tool_info.get("description") or "").strip()
    if len(description) > 400:
        description = description[:400] + "…"
    return {
        "name": tool_info.get("name"),
        "description": description,
        "required": required,
        # JSON-строка, как ожидает params в mcp_call_tool.
        "params_example": json.dumps(
            _build_args_example(schema, required), ensure_ascii=False
        ),
    }


@tool(
    description=(
        "Получить список инструментов конкретного MCP-сервера и схему их аргументов. "
        "Вызывай это ПЕРЕД mcp_call_tool, чтобы узнать имена инструментов и поля params. "
        "Аргумент server — имя сервера из списка доступных MCP-серверов."
    ),
)
async def mcp_get_info(
    server: Annotated[str, "Имя MCP-сервера из списка доступных"],
    runtime: ToolRuntime,
) -> dict | ToolMessage:
    owner_id = _owner_id(runtime)
    servers = await _all_servers(owner_id)
    target = _match_server(servers, server)
    if target is None:
        names = ", ".join(_server_label(s) for s in servers) or "<нет серверов>"
        return build_error_tool_message(
            content=f"MCP server '{server}' not found; available: {names}",
            runtime=runtime,
            tool_name="mcp_get_info",
        )
    try:
        tools = await list_server_tools(target, user_id=owner_id)
    except McpError as exc:
        return build_error_tool_message(
            content=_error_text(target, exc),
            runtime=runtime,
            tool_name="mcp_get_info",
        )

    return {
        "server": _server_label(target),
        "tools": [_describe_tool(t) for t in tools],
        "hint": (
            f"Вызов: mcp_call_tool(server='{_server_label(target)}', tool='<имя>', "
            "params='<JSON-строка из params_example>')"
        ),
    }


@tool(
    description=(
        "Вызвать инструмент MCP-сервера. server — имя сервера, tool — имя инструмента "
        "(узнай через mcp_get_info), params — JSON-строка с аргументами, например "
        '\'{"a": 1, "b": 2}\'. Если аргументы не нужны — params можно не передавать.'
    ),
)
async def mcp_call_tool(
    server: Annotated[str, "Имя MCP-сервера"],
    tool: Annotated[str, "Имя инструмента сервера"],
    runtime: ToolRuntime,
    params: Annotated[
        str | None,
        'JSON-строка с аргументами инструмента, например \'{"a": 1}\'. По умолчанию пусто.',
    ] = None,
) -> dict | ToolMessage:
    owner_id = _owner_id(runtime)

    def _error(message: str) -> ToolMessage:
        return build_error_tool_message(
            content=message, runtime=runtime, tool_name="mcp_call_tool"
        )

    parsed_params: dict[str, Any] = {}
    if params:
        try:
            parsed_params = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            return _error(
                'params должен быть JSON-строкой объекта, например \'{"key": "value"}\''
            )
        if not isinstance(parsed_params, dict):
            return _error(
                'params должен быть JSON-объектом, например \'{"key": "value"}\''
            )

    servers = await _all_servers(owner_id)
    target = _match_server(servers, server)
    if target is None:
        names = ", ".join(_server_label(s) for s in servers) or "<нет серверов>"
        return _error(f"MCP server '{server}' not found; available: {names}")

    # Validate the tool name against the (cached) catalog before calling.
    try:
        catalog = await list_server_tools(target, user_id=owner_id)
    except McpError as exc:
        return _error(_error_text(target, exc))

    tool_names = [t.get("name") for t in catalog]
    if tool not in tool_names:
        available = ", ".join(str(n) for n in tool_names) or "<нет>"
        return _error(
            f"server '{_server_label(target)}' has no tool '{tool}'; "
            f"available: {available}; call mcp_get_info('{_server_label(target)}')"
        )

    try:
        parts, is_error = await call_server_tool(
            target, tool, parsed_params, user_id=owner_id
        )
    except McpError as exc:
        return _error(_error_text(target, exc))

    data, attachments, message = await process_mcp_content(parts, runtime.config)

    if is_error:
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        return _error(f"tool '{tool}' on '{_server_label(target)}' returned an error: {text}")

    payload: dict[str, Any] = {"result": data}
    if message:
        payload["attachments"] = message
    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(payload, ensure_ascii=False),
        additional_kwargs={
            "tool_attachments": attachments,
            "tool_name": "mcp_call_tool",
        },
    )


def _error_text(server: ResolvedServer, exc: McpError) -> str:
    label = _server_label(server)
    if isinstance(exc, McpLocalBlockedError):
        return (
            f"server '{label}' points to a local/private host; local execution is "
            "disabled in this runtime"
        )
    if isinstance(exc, McpAuthRequiredError):
        return f"server '{label}' requires authorization; open MCP settings to connect"
    if isinstance(exc, McpTimeoutError):
        return f"server '{label}' did not respond (timeout)"
    if isinstance(exc, McpUnreachableError):
        return f"server '{label}' is unreachable"
    return f"server '{label}' error: {exc}"
