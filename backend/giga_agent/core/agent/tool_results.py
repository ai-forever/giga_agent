"""Helpers to build standardized error responses from @tool functions.

Most tools should let exceptions propagate — `ToolNode` converts them to
`ToolMessage(status="error")` automatically. Use these helpers only when a
tool needs to catch an exception and return a structured error itself
(typically because the success path returns a `Command` with state updates
that must be preserved, or because the original behavior swallowed the
exception and returned a plain success-shaped value).
"""

from __future__ import annotations

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command


def build_error_tool_message(
    content: str,
    *,
    runtime: ToolRuntime,
    tool_name: str,
    extra_additional_kwargs: dict | None = None,
) -> ToolMessage:
    """Build a ToolMessage with status='error' from inside a @tool function.

    `tool_name` is passed explicitly because `ToolRuntime` does not store it.
    `runtime.tool_call_id` is used to wire the message back to the originating
    tool call.
    """
    additional_kwargs: dict = {"tool_name": tool_name}
    if extra_additional_kwargs:
        additional_kwargs.update(extra_additional_kwargs)
    return ToolMessage(
        content=content,
        name=tool_name,
        tool_call_id=runtime.tool_call_id,
        status="error",
        additional_kwargs=additional_kwargs,
    )


def build_error_command(
    content: str,
    *,
    runtime: ToolRuntime,
    tool_name: str,
    extra_update: dict | None = None,
    extra_additional_kwargs: dict | None = None,
) -> Command:
    """Build a Command(update=...) whose ToolMessage has status='error'.

    Use this from tools whose success path returns a Command — keeping the
    return type consistent makes routing in `ToolNode._validate_tool_command`
    work without changes. `extra_update` lets the caller carry extra state
    fields besides `messages`.
    """
    tool_message = build_error_tool_message(
        content=content,
        runtime=runtime,
        tool_name=tool_name,
        extra_additional_kwargs=extra_additional_kwargs,
    )
    update: dict = {"messages": [tool_message]}
    if extra_update:
        update.update(extra_update)
    return Command(update=update)
