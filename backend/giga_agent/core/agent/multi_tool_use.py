"""Helpers for collapsing / expanding multi_tool_use parallel-call bundles."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from giga_agent.core.agent.tools import MULTI_TOOL_USE_NAME


def expand_multi_tool_use(output: AIMessage) -> AIMessage:
    """Expand multi_tool_use calls into individual tool_calls on the AIMessage.

    If the LLM returned a single `multi_tool_use` call containing N tool_uses,
    we replace it with N individual tool_calls so the ToolNode dispatches them
    in parallel as usual.
    """
    if not output.tool_calls:
        return output

    expanded: list[dict[str, Any]] = []
    changed = False

    for call in output.tool_calls:
        if call.get("name") != MULTI_TOOL_USE_NAME:
            expanded.append(call)
            continue

        changed = True
        args = call.get("args", {})
        tool_uses = args.get("tool_uses", [])

        for tu in tool_uses:
            recipient_name = (
                tu.get("recipient_name", "") if isinstance(tu, dict) else ""
            )
            raw_params = tu.get("parameters", "{}") if isinstance(tu, dict) else "{}"

            if isinstance(raw_params, str):
                try:
                    parameters = json.loads(raw_params)
                except (json.JSONDecodeError, TypeError):
                    parameters = {}
            elif isinstance(raw_params, dict):
                parameters = raw_params
            else:
                parameters = {}

            expanded.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": recipient_name,
                    "args": parameters,
                }
            )

    if not changed:
        return output

    return output.model_copy(update={"tool_calls": expanded})


def collapse_tool_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Collapse multiple ToolMessages following an AIMessage into one per AIMessage.

    For each AIMessage that has >1 tool_calls, we:
    1. Replace the AIMessage's tool_calls with a single `multi_tool_use` call.
    2. Merge all corresponding ToolMessages into one ToolMessage whose content
       is a JSON object mapping `tool_name` → `result`.

    This keeps the conversation compact for the LLM while preserving all data.
    """
    if not messages:
        return messages

    result: list[AnyMessage] = []
    i = 0

    while i < len(messages):
        msg = messages[i]

        if not isinstance(msg, AIMessage) or len(msg.tool_calls) <= 1:
            result.append(msg)
            i += 1
            continue

        ai_msg = msg
        tool_call_ids = {c["id"] for c in ai_msg.tool_calls}

        j = i + 1
        tool_msgs: list[ToolMessage] = []
        while j < len(messages) and isinstance(messages[j], ToolMessage):
            tm = cast("ToolMessage", messages[j])
            if tm.tool_call_id in tool_call_ids:
                tool_msgs.append(tm)
            j += 1

        if len(tool_msgs) <= 1:
            result.append(ai_msg)
            i += 1
            continue

        tc_id_to_name = {c["id"]: c.get("name", "") for c in ai_msg.tool_calls}

        tool_uses = []
        for call in ai_msg.tool_calls:
            tool_uses.append(
                {
                    "recipient_name": call.get("name", ""),
                    "parameters": json.dumps(call.get("args", {}), ensure_ascii=False),
                }
            )

        multi_call_id = str(uuid.uuid4())
        collapsed_ai = ai_msg.model_copy(
            update={
                "tool_calls": [
                    {
                        "id": multi_call_id,
                        "name": MULTI_TOOL_USE_NAME,
                        "args": {"tool_uses": tool_uses},
                    }
                ]
            }
        )

        merged_parts = []
        merged_attachments = []
        for tm in tool_msgs:
            tool_name = tc_id_to_name.get(tm.tool_call_id, tm.tool_call_id)
            merged_parts.append(f"[{tool_name}]: {tm.content}")
            tm_attachments = getattr(tm, "additional_kwargs", {}).get(
                "tool_attachments", []
            )
            if tm_attachments:
                merged_attachments.extend(tm_attachments)

        additional_kwargs: dict[str, Any] = {}
        if merged_attachments:
            additional_kwargs["tool_attachments"] = merged_attachments

        collapsed_tool = ToolMessage(
            tool_call_id=multi_call_id,
            content="\n---\n".join(merged_parts),
            additional_kwargs=additional_kwargs,
        )

        result.append(collapsed_ai)
        result.append(collapsed_tool)

        remaining_tool_ids = {tm.tool_call_id for tm in tool_msgs}
        for k in range(i + 1, j):
            m = messages[k]
            if isinstance(m, ToolMessage) and m.tool_call_id in remaining_tool_ids:
                continue
            result.append(m)

        i = j

    return result
