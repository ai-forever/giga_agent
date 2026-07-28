"""Helpers for invoking one tool from inside another.

Some tools dispatch to other ``BaseTool``s in-process — the ``python`` REPL tool
runs agent tools from generated code, and the connector meta-tools
(``connector_call_tool``) call the tools of lazy modules / MCP servers. Both need
to invoke an inner tool with the *parent* tool's ``ToolRuntime`` so the inner
tool sees the same config/state/agent.
"""

from __future__ import annotations

import inspect
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from giga_agent.core.agent.tool_policy import blocked_tool_message, is_tool_allowed


def tool_accepts_parameter(tool_or_callable: Any, param_name: str) -> bool:
    """True if the tool's underlying callable declares ``param_name``.

    For a ``BaseTool`` this inspects its ``coroutine``/``func`` (the wrapped
    function), since the tool object itself has no such signature.
    """
    candidate = tool_or_callable
    if isinstance(tool_or_callable, BaseTool):
        candidate = (
            getattr(tool_or_callable, "coroutine", None)
            or getattr(tool_or_callable, "func", None)
            or tool_or_callable
        )
    try:
        signature = inspect.signature(candidate)
    except (TypeError, ValueError):
        return False
    return param_name in signature.parameters


async def invoke_inner_tool(
    tool_: BaseTool,
    kwargs: dict[str, Any],
    runtime: ToolRuntime,
) -> Any:
    """Invoke ``tool_`` with the parent ``runtime`` and return its raw output.

    The inner tool receives the same ``runtime`` (and thus config/state/agent)
    as the dispatching tool. We invoke via ``ainvoke`` so InjectedState/Store and
    other framework injections still work; on a schema mismatch we fall back to
    calling the raw coroutine/func directly with the injected ``runtime``.
    """
    state = getattr(runtime, "state", None)
    mode = state.get("mode") if isinstance(state, dict) else None
    if not is_tool_allowed(tool_, mode, args=kwargs):
        return blocked_tool_message(
            tool_.name,
            getattr(runtime, "tool_call_id", tool_.name),
        )

    call_kwargs = dict(kwargs)
    if tool_accepts_parameter(tool_, "runtime"):
        call_kwargs.setdefault("runtime", runtime)
    try:
        return await tool_.ainvoke(call_kwargs, config=runtime.config)
    except ValidationError:
        raw_callable = getattr(tool_, "coroutine", None) or getattr(tool_, "func", None)
        if raw_callable is None:
            raise
        result = raw_callable(**call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
