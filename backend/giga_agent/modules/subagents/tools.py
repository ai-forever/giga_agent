from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from cashews import cache
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph.ui import push_ui_message
from langgraph.types import Command, interrupt

from giga_agent.channels.telegram.utils import _extract_ai_response
from giga_agent.conf import get_settings
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.db import get_session_factory
from giga_agent.core.integrations.registry import get_current_agent
from giga_agent.modules.subagents_legacy.runtime import invoke_subgraph_cli
from giga_agent.subagents.leases import (
    SubagentConcurrencyError,
    acquire_lease,
    release_lease,
    update_lease,
)
from giga_agent.utils.langgraph_sdk import client_session

TOOL_NAME = "subtask"
THREAD_RESULT_TOOL_NAME = "thread_result"
SUBAGENT_GRAPH_ID = "giga_agent_subtask"
SUBAGENT_STREAM_SCOPE = "subagent"
_SESSION_TTL = "24h"
_CLI_THREAD_KEY = "subagents:cli-thread:{user_id}:{thread_id}"
_ACTIVE_RUN_STATUSES = {"pending", "running", "interrupting", "interrupted"}
_FAILED_RUN_STATUSES = {"error", "failed", "timeout", "cancelled"}
_MAX_ACTIVE_TOOL_ARGS = 1200
_SENSITIVE_ARG_NAMES = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


async def _heartbeat(user_id, lease_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            await update_lease(user_id, lease_id)
    except asyncio.CancelledError:
        return


def _result_text(result: dict[str, Any]) -> str:
    text, _ = _extract_ai_response(result)
    if text:
        return text
    _, final_text = _last_final_ai_message(list(result.get("messages") or []))
    if final_text:
        return final_text
    return "Суб-агент завершился без текстового ответа."


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(key, default)
    return getattr(message, key, default)


def _message_type(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("type") or message.get("role") or "")
    return str(_message_value(message, "type", ""))


def _message_tool_calls(message: Any) -> list[Any]:
    return list(_message_value(message, "tool_calls", []) or [])


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str) and block.strip():
            parts.append(block.strip())
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _last_final_ai_message(messages: list[Any]) -> tuple[str | None, str | None]:
    for message in reversed(messages):
        if _message_type(message) != "ai" or _message_tool_calls(message):
            continue
        content = _message_content_text(_message_value(message, "content", ""))
        if content:
            return _message_value(message, "id"), content
    return None, None


def _safe_tool_value(value: Any, *, key: str | None = None) -> Any:
    if key and any(part in key.lower() for part in _SENSITIVE_ARG_NAMES):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _safe_tool_value(item_value, key=str(item_key))
            for item_key, item_value in list(value.items())[:20]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_tool_value(item) for item in list(value)[:20]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def _active_tool(messages: list[Any]) -> dict[str, str] | None:
    completed_call_ids = {
        _message_value(message, "tool_call_id")
        for message in messages
        if _message_type(message) == "tool"
    }
    for message in reversed(messages):
        calls = _message_tool_calls(message) if _message_type(message) == "ai" else []
        for call in reversed(calls):
            call_id = _message_value(call, "id")
            if call_id and call_id in completed_call_ids:
                continue
            name = _message_value(call, "name", "unknown")
            args = _message_value(call, "args", {})
            try:
                rendered_args = json.dumps(
                    _safe_tool_value(args), ensure_ascii=False, default=str
                )
            except Exception:
                rendered_args = str(args)
            return {
                "name": str(name),
                "args": rendered_args[:_MAX_ACTIVE_TOOL_ARGS],
            }
    return None


def _state_values(state: Any) -> dict[str, Any]:
    values = state.get("values") if isinstance(state, dict) else getattr(state, "values", {})
    return values if isinstance(values, dict) else {}


def _state_messages(state: Any) -> list[Any]:
    return list(_state_values(state).get("messages") or [])


def _serialize_thread_message(message: Any, *, include_tool_calls: bool) -> dict[str, Any]:
    message_type = _message_type(message)
    serialized: dict[str, Any] = {
        "type": message_type,
        "id": _message_value(message, "id"),
        "content": _message_value(message, "content", ""),
    }
    if message_type == "ai" and include_tool_calls:
        calls = []
        for call in _message_tool_calls(message):
            calls.append(
                {
                    "id": _message_value(call, "id"),
                    "name": _message_value(call, "name", "unknown"),
                    "args": _safe_tool_value(_message_value(call, "args", {})),
                }
            )
        if calls:
            serialized["tool_calls"] = calls
    if message_type == "tool":
        serialized.update(
            {
                "tool_call_id": _message_value(message, "tool_call_id"),
                "name": _message_value(message, "name"),
                "status": _message_value(message, "status"),
            }
        )
    return serialized


def _thread_messages(
    messages: list[Any],
    *,
    limit: int,
    offset: int,
    include: list[str] | None,
) -> tuple[list[dict[str, Any]], bool, int]:
    include_tool_calls = "tool_calls" in (include or [])
    allowed_types = {"human", "ai", "tool"} if include_tool_calls else {"human", "ai"}
    filtered = [
        message
        for message in messages
        if _message_type(message) in allowed_types
        and (
            include_tool_calls
            or _message_type(message) == "human"
            or (_message_type(message) == "ai" and not _message_tool_calls(message))
        )
    ]
    newest_first = list(reversed(filtered))
    page = newest_first[offset : offset + limit]
    serialized = [
        _serialize_thread_message(message, include_tool_calls=include_tool_calls)
        for message in page
    ]
    return serialized, offset + len(page) < len(newest_first), len(newest_first)


def _run_value(run: Any, key: str, default: Any = None) -> Any:
    if isinstance(run, dict):
        return run.get(key, default)
    return getattr(run, key, default)


def _run_status(run: Any) -> str:
    return str(_run_value(run, "status", "")).lower()


def _latest_run(runs: list[Any]) -> Any | None:
    if not runs:
        return None
    with_timestamps = [run for run in runs if _run_value(run, "created_at")]
    if with_timestamps:
        return max(with_timestamps, key=lambda run: str(_run_value(run, "created_at")))
    return runs[0]


def _cli_thread_key(user_id: Any, thread_id: str) -> str:
    return _CLI_THREAD_KEY.format(user_id=user_id, thread_id=thread_id)


def _structured_content(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _tool_result(
    runtime: ToolRuntime,
    *,
    content: str,
    snapshot: dict[str, Any],
    is_error: bool = False,
    result: dict[str, Any] | None = None,
    name: str = TOOL_NAME,
    include_activity: bool = True,
) -> Command:
    additional_kwargs: dict[str, Any] = {}
    if include_activity:
        additional_kwargs["subagent_activity"] = snapshot
    if result is not None:
        additional_kwargs["subagent_result"] = result
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    name=name,
                    tool_call_id=runtime.tool_call_id,
                    status="error" if is_error else "success",
                    additional_kwargs=additional_kwargs,
                )
            ]
        }
    )


def _subtask_result(
    runtime: ToolRuntime,
    *,
    snapshot: dict[str, Any],
    status: str,
    content: str = "",
    error: str | None = None,
    error_code: str | None = None,
    child_run_id: str | None = None,
) -> Command:
    result: dict[str, Any] = {
        "status": status,
        "thread_id": snapshot.get("child_thread_id"),
        "agent_id": snapshot.get("agent_id"),
        "child_run_id": child_run_id or snapshot.get("child_run_id"),
        "content": content,
    }
    if error is not None:
        result["error"] = error
    if error_code is not None:
        result["error_code"] = error_code
    return _tool_result(
        runtime,
        content=_structured_content(result),
        snapshot=snapshot,
        is_error=status in {"error", "not_found", "busy"},
        result=result,
    )


def _push_subagent_activity(activity: dict[str, Any]) -> None:
    """Stream activity without writing to the graph's optional ``ui`` state."""
    push_ui_message("subagent_activity", activity, state_key=None)


async def _resolve_definition(
    agent,
    user,
    agent_id: str | None,
    *,
    cli: bool,
    config=None,
):
    if not agent_id:
        return None
    if cli:
        return await agent.subagent_registry.resolve_for_cli(
            user,
            agent_id,
            require_runnable=True,
            config=config,
        )
    factory = await get_session_factory()
    async with factory() as session:
        return await agent.subagent_registry.resolve(
            session,
            user,
            agent_id,
            require_runnable=True,
            cli=cli,
            config=config,
        )


async def _inspect_server_thread(runtime: ToolRuntime, thread_id: str):
    async with client_session(runtime.config) as client:
        thread = await client.threads.get(thread_id)
        state = await client.threads.get_state(thread_id)
        runs = await client.runs.list(thread_id, limit=20)
    return thread, state, list(runs or [])


async def _validate_subagent_thread(
    runtime: ToolRuntime,
    *,
    agent,
    user,
    thread_id: str,
    requested_agent_id: str | None,
) -> tuple[Any | None, dict[str, Any] | None, Any | None, list[Any], str | None]:
    cli = get_settings().giga_agent_runtime == "cli"
    if cli:
        registered = await cache.get(_cli_thread_key(user.id, thread_id))
        if not isinstance(registered, dict):
            return None, None, None, [], "not_found"
        metadata = {"subagent": True, "agent_id": registered.get("agent_id")}
        from langgraph.constants import CONFIG_KEY_CHECKPOINTER

        parent_configurable = {
            key: value
            for key, value in ((runtime.config or {}).get("configurable") or {}).items()
            if key not in {"checkpoint_ns", "checkpoint_id", "checkpoint_map"}
        }
        state = await agent.graph.aget_state(
            {
                "configurable": {
                    **parent_configurable,
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "subagent_id": registered.get("agent_id"),
                    CONFIG_KEY_CHECKPOINTER: parent_configurable.get(
                        CONFIG_KEY_CHECKPOINTER
                    ),
                }
            }
        )
        runs: list[Any] = []
    else:
        try:
            thread, state, runs = await _inspect_server_thread(runtime, thread_id)
        except Exception:
            return None, None, None, [], "not_found"
        metadata = thread.get("metadata") if isinstance(thread, dict) else None
        if not isinstance(metadata, dict) or metadata.get("subagent") is not True:
            return None, None, None, [], "not_found"

    stored_agent_id = metadata.get("agent_id")
    if not stored_agent_id or (
        requested_agent_id is not None and requested_agent_id != stored_agent_id
    ):
        return None, metadata, state, runs, "agent_mismatch"
    definition = await _resolve_definition(
        agent,
        user,
        str(stored_agent_id),
        cli=cli,
        config=runtime.config,
    )
    if definition is None:
        return None, metadata, state, runs, "not_found"
    return definition, metadata, state, runs, None


async def _validate_thread_for_result(
    runtime: ToolRuntime,
    *,
    agent,
    user,
    thread_id: str,
) -> tuple[dict[str, Any] | None, Any | None, list[Any], str | None]:
    """Resolve any thread visible to the current user for read-only inspection."""
    cli = get_settings().giga_agent_runtime == "cli"
    if cli:
        registered = await cache.get(_cli_thread_key(user.id, thread_id))
        current_thread_id = ((runtime.config or {}).get("configurable") or {}).get(
            "thread_id"
        )
        if not isinstance(registered, dict) and str(current_thread_id) != thread_id:
            return None, None, [], "not_found"
        from langgraph.constants import CONFIG_KEY_CHECKPOINTER

        parent_configurable = {
            key: value
            for key, value in ((runtime.config or {}).get("configurable") or {}).items()
            if key not in {"checkpoint_ns", "checkpoint_id", "checkpoint_map"}
        }
        stored_agent_id = registered.get("agent_id") if registered else None
        state = await agent.graph.aget_state(
            {
                "configurable": {
                    **parent_configurable,
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    **({"subagent_id": stored_agent_id} if stored_agent_id else {}),
                    CONFIG_KEY_CHECKPOINTER: parent_configurable.get(
                        CONFIG_KEY_CHECKPOINTER
                    ),
                }
            }
        )
        return (
            {
                "subagent": bool(stored_agent_id),
                "agent_id": stored_agent_id,
            },
            state,
            [],
            None,
        )

    try:
        thread, state, runs = await _inspect_server_thread(runtime, thread_id)
    except Exception:
        return None, None, [], "not_found"
    metadata = thread.get("metadata") if isinstance(thread, dict) else None
    return (dict(metadata) if isinstance(metadata, dict) else {}), state, runs, None


def _busy_run(runs: list[Any]) -> Any | None:
    return next((run for run in runs if _run_status(run) in _ACTIVE_RUN_STATUSES), None)


def _result_from_thread_state(
    *,
    thread_id: str,
    agent_id: str | None,
    state: Any,
    runs: list[Any],
    kind: str = "subagent",
    limit: int = 10,
    offset: int = 0,
    include: list[str] | None = None,
) -> dict[str, Any]:
    messages = _state_messages(state)
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    page, has_more, total_messages = _thread_messages(
        messages,
        limit=limit,
        offset=offset,
        include=include,
    )
    latest_run = _latest_run(runs)
    busy = _busy_run(runs)
    message_id, content = _last_final_ai_message(messages)
    result: dict[str, Any] = {
        "status": "empty",
        "thread_id": thread_id,
        "kind": kind,
        "agent_id": agent_id,
        "message_id": message_id,
        "messages": page,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "total_messages": total_messages,
    }
    if busy is not None:
        result["status"] = "running"
        active_tool = _active_tool(messages)
        if active_tool is not None:
            result["active_tool"] = active_tool
        result["run_id"] = _run_value(busy, "run_id")
    elif latest_run is not None and _run_status(latest_run) in _FAILED_RUN_STATUSES:
        result["status"] = "failed"
        result["run_id"] = _run_value(latest_run, "run_id")
    elif content:
        result["status"] = "completed"
    return result


async def _parent_metadata(runtime: ToolRuntime) -> dict[str, Any]:
    configurable = (runtime.config or {}).get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if not thread_id or get_settings().giga_agent_runtime == "cli":
        return {}
    async with client_session(runtime.config) as client:
        try:
            parent = await client.threads.get(thread_id)
        except Exception:
            return {}
    metadata = parent.get("metadata") if isinstance(parent, dict) else None
    return dict(metadata) if isinstance(metadata, dict) else {}


async def _resolve_thread_result_state(
    runtime: ToolRuntime,
    *,
    agent,
    user,
    thread_id: str,
    metadata: dict[str, Any],
    state: Any,
    runs: list[Any],
) -> tuple[dict[str, Any], Any, list[Any]]:
    """Use an experimental thread's inner state when it is available."""
    inner_thread_id = _state_values(state).get("inner_thread_id")
    if not isinstance(inner_thread_id, str) or not inner_thread_id.strip():
        return metadata, state, runs
    inner_thread_id = inner_thread_id.strip()
    if inner_thread_id == thread_id:
        return metadata, state, runs

    try:
        (
            inner_metadata,
            inner_state,
            inner_runs,
            validation_error,
        ) = await _validate_thread_for_result(
            runtime,
            agent=agent,
            user=user,
            thread_id=inner_thread_id,
        )
    except Exception:
        return metadata, state, runs

    if validation_error is not None or inner_metadata is None or inner_state is None:
        return metadata, state, runs
    return inner_metadata, inner_state, inner_runs


def _session_key(parent_thread_id: str | None, tool_call_id: str) -> str:
    return f"subagents:session:{parent_thread_id or 'temporary'}:{tool_call_id}"


def _interrupt_value(snapshot: dict[str, Any]) -> Any | None:
    interrupts = snapshot.get("interrupts") or []
    if not interrupts:
        return None
    first = interrupts[0]
    value = first.get("value") if isinstance(first, dict) else first
    if isinstance(value, dict) and not value.get("tools"):
        messages = (snapshot.get("values") or {}).get("messages") or []
        for message in reversed(messages):
            tool_calls = (
                message.get("tool_calls")
                if isinstance(message, dict)
                else getattr(message, "tool_calls", None)
            )
            if tool_calls:
                value = {**value, "tools": tool_calls}
                break
    return value


def _approval_payload(
    *,
    definition,
    child_thread_id: str,
    child_run_id: str,
    value: Any,
) -> dict[str, Any]:
    inner = value if isinstance(value, dict) else {"value": value}
    return {
        "type": "subagent_approval",
        "agent_id": definition.ref,
        "agent_name": definition.name,
        "child_thread_id": child_thread_id,
        "child_run_id": child_run_id,
        "tools": inner.get("tools") or [],
        "inner_interrupt": inner,
    }


def _build_subagent_thread_metadata(
    *,
    definition,
    parent_thread_id: str | None,
    parent_run_id: str | None,
    tool_call_id: str,
    auto_approve: bool,
    parent_plan_mode: bool,
    project_id: Any | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "type": "subagent",
        "subagent": True,
        "agent_id": definition.ref,
        "parent_thread_id": parent_thread_id,
        "parent_run_id": parent_run_id,
        "tool_call_id": tool_call_id,
        "auto_approve": auto_approve,
        "subagent_parent_plan_mode": parent_plan_mode,
        "graph_id": SUBAGENT_GRAPH_ID,
    }
    if project_id:
        metadata["project_id"] = str(project_id)
    return metadata


def _sync_activity(snapshot: dict[str, Any], state: dict[str, Any]) -> None:
    items = snapshot.setdefault("items", [])
    by_id = {item.get("id"): item for item in items if item.get("id")}
    for message in (state.get("values") or {}).get("messages") or []:
        message_type = (
            message.get("type")
            if isinstance(message, dict)
            else getattr(message, "type", None)
        )
        if message_type == "ai":
            calls = (
                message.get("tool_calls")
                if isinstance(message, dict)
                else getattr(message, "tool_calls", None)
            ) or []
            for call in calls:
                call_id = call.get("id")
                if call_id and call_id not in by_id and call.get("name") != "think":
                    item = {
                        "type": "tool",
                        "id": call_id,
                        "name": call.get("name"),
                        "status": "running",
                        "started_at": time.time(),
                    }
                    items.append(item)
                    by_id[call_id] = item
        elif message_type == "tool":
            call_id = (
                message.get("tool_call_id")
                if isinstance(message, dict)
                else getattr(message, "tool_call_id", None)
            )
            item = by_id.get(call_id)
            if item is not None and item.get("status") == "running":
                status = (
                    message.get("status")
                    if isinstance(message, dict)
                    else getattr(message, "status", None)
                )
                item["status"] = status or "success"
                item["finished_at"] = time.time()


async def _run_server_child(
    runtime: ToolRuntime,
    *,
    child_thread_id: str,
    child_configurable: dict[str, Any],
    lease_user_id,
    lease_id: str,
    run_input: dict[str, Any] | None = None,
    resume: Any | None = None,
    activity: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, Any | None]:
    async with client_session(runtime.config) as client:
        kwargs: dict[str, Any] = {
            "assistant_id": SUBAGENT_GRAPH_ID,
            "config": {"configurable": child_configurable},
            "stream_mode": ["values", "updates"],
        }
        if run_input is not None:
            kwargs["input"] = run_input
        if resume is not None:
            kwargs["command"] = {"resume": resume}
        run = await client.runs.create(child_thread_id, **kwargs)
        child_run_id = run["run_id"]
        await update_lease(
            lease_user_id,
            lease_id,
            state="running",
            child_run_id=child_run_id,
        )
        try:
            while True:
                run_state = await client.runs.get(child_thread_id, child_run_id)
                snapshot = await client.threads.get_state(child_thread_id)
                if activity is not None:
                    _sync_activity(activity, snapshot)
                    activity["child_run_id"] = child_run_id
                    _push_subagent_activity(activity)
                if run_state.get("status") not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.5)
            result = await client.runs.join(child_thread_id, child_run_id)
        except asyncio.CancelledError:
            await client.runs.cancel(child_thread_id, child_run_id)
            raise
        snapshot = await client.threads.get_state(child_thread_id)
    if not isinstance(result, dict):
        result = snapshot.get("values") or {}
    return result, child_run_id, _interrupt_value(snapshot)


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.DELEGATED))
async def subtask(
    task: str,
    runtime: ToolRuntime,
    agent_id: str | None = None,
    thread_id: str | None = None,
) -> Command:
    """Передаёт отдельную задачу специализированному суб-агенту.

    Args:
        task: Самодостаточное описание задачи без скрытых изменений runtime или permissions.
        agent_id: Точный идентификатор суб-агента. Необязателен при продолжении thread_id.
        thread_id: Идентификатор ранее созданного subagent-thread для продолжения.
    """
    if runtime is None:
        raise ValueError("ToolRuntime is required")
    agent = get_current_agent()
    if agent is None:
        raise RuntimeError("GigaAgent runtime is unavailable")
    resolver = RuntimeResolver.from_config(runtime.config)
    user = resolver.user
    cli = get_settings().giga_agent_runtime == "cli"
    continuation = bool(thread_id)
    target_metadata: dict[str, Any] = {}
    target_runs: list[Any] = []
    if continuation:
        (
            definition,
            target_metadata,
            _,
            target_runs,
            validation_error,
        ) = await _validate_subagent_thread(
            runtime,
            agent=agent,
            user=user,
            thread_id=str(thread_id),
            requested_agent_id=agent_id,
        )
        if validation_error is not None or definition is None:
            result_status = (
                "error" if validation_error == "agent_mismatch" else validation_error
            ) or "not_found"
            snapshot = {
                "agent_id": agent_id,
                "task": task,
                "child_thread_id": thread_id,
                "status": result_status,
            }
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status=result_status,
                error=(
                    "Thread is not an accessible subagent thread"
                    if validation_error == "not_found"
                    else "The requested agent does not match the subagent thread"
                ),
                error_code=validation_error,
            )
        if not isinstance(target_metadata, dict):
            snapshot = {
                "agent_id": definition.ref,
                "agent_name": definition.name,
                "task": task,
                "child_thread_id": thread_id,
                "status": "error",
            }
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status="error",
                error="Invalid metadata for the subagent thread",
                error_code="SUBAGENT_METADATA_INVALID",
            )
        busy = _busy_run(target_runs)
        if busy is not None:
            snapshot = {
                "agent_id": definition.ref,
                "agent_name": definition.name,
                "task": task,
                "child_thread_id": thread_id,
                "child_run_id": _run_value(busy, "run_id"),
                "status": "busy",
            }
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status="busy",
                error="The subagent thread already has an active run",
                error_code="SUBAGENT_THREAD_BUSY",
            )
    else:
        if not agent_id:
            snapshot = {"task": task, "status": "error"}
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status="error",
                error="agent_id is required when thread_id is not provided",
                error_code="SUBAGENT_AGENT_ID_REQUIRED",
            )
        definition = await _resolve_definition(
            agent,
            user,
            agent_id,
            cli=cli,
            config=runtime.config,
        )
        if definition is None:
            snapshot = {"agent_id": agent_id, "task": task, "status": "needs_setup"}
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status="not_found",
                error=f"Суб-агент {agent_id!r} выключен, недоступен или требует настройки.",
                error_code="SUBAGENT_NOT_READY",
            )

    configurable = dict((runtime.config or {}).get("configurable") or {})
    parent_metadata = await _parent_metadata(runtime) if not continuation else {}
    project_id = (
        target_metadata.get("project_id")
        if continuation
        else parent_metadata.get("project_id") or configurable.get("project_id")
    )
    parent_thread_id = (
        target_metadata.get("parent_thread_id")
        if continuation
        else configurable.get("thread_id")
    )
    parent_run_id = (
        target_metadata.get("parent_run_id")
        if continuation
        else configurable.get("run_id")
    )
    session_key = _session_key(parent_thread_id, runtime.tool_call_id)
    session_data = None if continuation else await cache.get(session_key)
    if not isinstance(session_data, dict):
        session_data = None

    if continuation:
        child_thread_id = str(thread_id)
        try:
            lease = await acquire_lease(user.id, child_thread_id=child_thread_id)
        except SubagentConcurrencyError as exc:
            snapshot = {
                "agent_id": definition.ref,
                "task": task,
                "child_thread_id": child_thread_id,
                "status": "error",
                "error_code": exc.code,
            }
            return _subtask_result(
                runtime,
                snapshot=snapshot,
                status="error",
                error=str(exc),
                error_code=exc.code,
            )
        session_data = {
            "agent_id": definition.ref,
            "child_thread_id": child_thread_id,
            "lease_id": lease.id,
            "started_at": time.time(),
            "started": True,
            "approvals": [],
        }
        started_at = time.time()
    elif session_data is None:
        child_thread_id = str(uuid.uuid4())
        try:
            lease = await acquire_lease(user.id, child_thread_id=child_thread_id)
        except SubagentConcurrencyError as exc:
            return _subtask_result(
                runtime,
                snapshot={
                    "agent_id": definition.ref,
                    "task": task,
                    "status": "error",
                    "error_code": exc.code,
                },
                status="error",
                error=str(exc),
                error_code=exc.code,
            )
        started_at = time.time()
        session_data = {
            "agent_id": definition.ref,
            "child_thread_id": child_thread_id,
            "lease_id": lease.id,
            "started_at": started_at,
            "started": False,
            "approvals": [],
        }
        await cache.set(session_key, session_data, expire=_SESSION_TTL)
    else:
        if session_data.get("agent_id") != definition.ref:
            raise RuntimeError("Subagent resume identity mismatch")
        child_thread_id = str(session_data["child_thread_id"])
        started_at = float(session_data.get("started_at") or time.time())

    lease_id = str(session_data["lease_id"])
    heartbeat_task = asyncio.create_task(_heartbeat(user.id, lease_id))
    preserve_session = False
    auto_approve = bool(
        target_metadata.get("auto_approve", False)
        if continuation
        else parent_metadata.get("auto_approve", configurable.get("auto_approve", False))
    )
    parent_plan_mode = bool(
        target_metadata.get("subagent_parent_plan_mode", False)
        if continuation
        else getattr(runtime, "state", {}).get("mode") == "plan"
    )
    snapshot: dict[str, Any] = {
        "agent_id": definition.ref,
        "agent_name": definition.name,
        "task": task,
        "tool_call_id": runtime.tool_call_id,
        "child_thread_id": child_thread_id,
        "status": "running",
        "started_at": started_at,
        "items": [],
    }
    _push_subagent_activity(snapshot)
    try:
        child_configurable = {
            "subagent_id": definition.ref,
            "subagent_parent_plan_mode": parent_plan_mode,
            "auto_approve": auto_approve,
            "memory_disabled": True,
        }
        if project_id:
            child_configurable["project_id"] = str(project_id)
        run_input = {
            "messages": [
                HumanMessage(
                    content=task,
                    additional_kwargs={"user_input": task, "subagent_task": True},
                )
            ],
            "mcp_tools": [],
        }
        interrupt_value = None
        child_run_id: str | None = None
        result: dict[str, Any] = {}
        if cli:
            if not continuation:
                await cache.set(
                    _cli_thread_key(user.id, child_thread_id),
                    {"agent_id": definition.ref},
                    expire=_SESSION_TTL,
                )
            result = await invoke_subgraph_cli(
                agent.graph,
                run_input,
                runtime,
                thread_id=child_thread_id,
                extra_configurable=child_configurable,
                extra_metadata={"giga_agent_scope": SUBAGENT_STREAM_SCOPE},
            )
        elif continuation:
            result, child_run_id, interrupt_value = await _run_server_child(
                runtime,
                child_thread_id=child_thread_id,
                child_configurable=child_configurable,
                lease_user_id=user.id,
                lease_id=lease_id,
                run_input=run_input,
                activity=snapshot,
            )
        elif not session_data.get("started"):
            metadata = _build_subagent_thread_metadata(
                definition=definition,
                parent_thread_id=parent_thread_id,
                parent_run_id=parent_run_id,
                tool_call_id=runtime.tool_call_id,
                auto_approve=auto_approve,
                parent_plan_mode=parent_plan_mode,
                project_id=project_id,
            )
            async with client_session(runtime.config) as client:
                thread = await client.threads.create(
                    thread_id=child_thread_id, metadata=metadata
                )
                child_thread_id = thread["thread_id"]
            session_data["child_thread_id"] = child_thread_id
            await cache.set(session_key, session_data, expire=_SESSION_TTL)
            result, child_run_id, interrupt_value = await _run_server_child(
                runtime,
                child_thread_id=child_thread_id,
                child_configurable=child_configurable,
                lease_user_id=user.id,
                lease_id=lease_id,
                run_input=run_input,
                activity=snapshot,
            )
            session_data["started"] = True
            await cache.set(session_key, session_data, expire=_SESSION_TTL)

        if get_settings().giga_agent_runtime != "cli":
            approvals = session_data.setdefault("approvals", [])
            if interrupt_value is not None:
                payload = _approval_payload(
                    definition=definition,
                    child_thread_id=child_thread_id,
                    child_run_id=child_run_id or "",
                    value=interrupt_value,
                )
                approvals.append({"payload": payload, "applied": False})
                await cache.set(session_key, session_data, expire=_SESSION_TTL)

            for approval in approvals:
                if not approval.get("applied"):
                    snapshot.update(
                        {
                            "status": "interrupted",
                            "approval": approval["payload"],
                            "expires_at": time.time()
                            + get_settings().giga_agent_subagent_approval_ttl_seconds,
                        }
                    )
                    _push_subagent_activity(snapshot)
                preserve_session = True
                answer = interrupt(approval["payload"])
                preserve_session = False
                if approval.get("applied"):
                    continue
                snapshot["status"] = "running"
                snapshot.pop("approval", None)
                result, child_run_id, interrupt_value = await _run_server_child(
                    runtime,
                    child_thread_id=child_thread_id,
                    child_configurable=child_configurable,
                    lease_user_id=user.id,
                    lease_id=lease_id,
                    resume=answer,
                    activity=snapshot,
                )
                approval["applied"] = True
                await cache.set(session_key, session_data, expire=_SESSION_TTL)
                if interrupt_value is not None:
                    payload = _approval_payload(
                        definition=definition,
                        child_thread_id=child_thread_id,
                        child_run_id=child_run_id,
                        value=interrupt_value,
                    )
                    approvals.append({"payload": payload, "applied": False})
                    await cache.set(session_key, session_data, expire=_SESSION_TTL)
            snapshot["child_run_id"] = child_run_id
        final = _result_text(result)
        snapshot.update(
            {
                "child_thread_id": child_thread_id,
                "status": "completed",
                "finished_at": time.time(),
                "duration": time.time() - started_at,
                "result": final,
            }
        )
        _push_subagent_activity(snapshot)
        return _subtask_result(
            runtime,
            snapshot=snapshot,
            status="completed",
            content=final,
            child_run_id=child_run_id,
        )
    except asyncio.CancelledError:
        snapshot.update(
            {
                "status": "cancelled",
                "finished_at": time.time(),
                "duration": time.time() - started_at,
            }
        )
        _push_subagent_activity(snapshot)
        raise
    except Exception as exc:
        snapshot.update(
            {
                "status": "error",
                "finished_at": time.time(),
                "duration": time.time() - started_at,
                "error": str(exc),
            }
        )
        _push_subagent_activity(snapshot)
        return _subtask_result(
            runtime,
            snapshot=snapshot,
            status="error",
            error=f"Ошибка запуска суб-агента: {exc}",
            child_run_id=child_run_id,
        )
    finally:
        heartbeat_task.cancel()
        await heartbeat_task
        if preserve_session:
            await update_lease(user.id, lease_id, state="interrupted")
        else:
            await cache.delete(session_key)
            await release_lease(user.id, lease_id)


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def thread_result(
    thread_id: str,
    runtime: ToolRuntime,
    limit: int = 10,
    offset: int = 0,
    include: list[str] | None = None,
) -> Command:
    """Возвращает состояние и страницу сообщений пользовательского thread.

    Args:
        thread_id: Идентификатор пользовательского thread.
        limit: Количество сообщений в странице, максимум 50.
        offset: Смещение от самых новых сообщений.
        include: Дополнительные данные. Значение ``tool_calls`` добавляет
            AI tool-call сообщения и связанные ToolMessage.
    """
    if runtime is None:
        raise ValueError("ToolRuntime is required")
    agent = get_current_agent()
    if agent is None:
        raise RuntimeError("GigaAgent runtime is unavailable")
    resolver = RuntimeResolver.from_config(runtime.config)
    user = resolver.user
    try:
        metadata, state, runs, validation_error = await _validate_thread_for_result(
            runtime,
            agent=agent,
            user=user,
            thread_id=thread_id,
        )
    except Exception:
        metadata = state = None
        runs = []
        validation_error = "not_found"

    if validation_error is not None or metadata is None:
        result = {
            "status": "not_found",
            "thread_id": thread_id,
            "kind": None,
            "agent_id": None,
            "message_id": None,
            "content": "",
        }
        return _tool_result(
            runtime,
            content=_structured_content(result),
            snapshot={"thread_id": thread_id, "status": "not_found"},
            is_error=True,
            result=result,
            name=THREAD_RESULT_TOOL_NAME,
            include_activity=False,
        )

    metadata, state, runs = await _resolve_thread_result_state(
        runtime,
        agent=agent,
        user=user,
        thread_id=thread_id,
        metadata=metadata,
        state=state,
        runs=runs,
    )
    is_subagent = metadata.get("subagent") is True
    result = _result_from_thread_state(
        thread_id=thread_id,
        kind="subagent" if is_subagent else "user",
        agent_id=metadata.get("agent_id") if is_subagent else None,
        state=state,
        runs=runs,
        limit=limit,
        offset=offset,
        include=include,
    )
    return _tool_result(
        runtime,
        content=_structured_content(result),
        snapshot={
            "thread_id": thread_id,
            "agent_id": result["agent_id"],
            "status": result["status"],
        },
        result=result,
        name=THREAD_RESULT_TOOL_NAME,
        include_activity=False,
    )
