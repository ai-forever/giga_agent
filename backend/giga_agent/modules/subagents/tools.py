from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from cashews import cache
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
_SESSION_TTL = "24h"


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
    for message in reversed(result.get("messages") or []):
        if isinstance(message, AIMessage) and not message.tool_calls:
            if isinstance(message.content, str) and message.content.strip():
                return message.content.strip()
    return "Суб-агент завершился без текстового ответа."


def _tool_result(
    runtime: ToolRuntime,
    *,
    content: str,
    snapshot: dict[str, Any],
    is_error: bool = False,
) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    name=TOOL_NAME,
                    tool_call_id=runtime.tool_call_id,
                    status="error" if is_error else "success",
                    additional_kwargs={"subagent_activity": snapshot},
                )
            ]
        }
    )


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
            "assistant_id": "giga_agent",
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
                    push_ui_message("subagent_activity", activity)
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
async def subtask(task: str, agent_id: str, runtime: ToolRuntime) -> Command:
    """Передаёт отдельную задачу специализированному суб-агенту.

    Args:
        task: Самодостаточное описание задачи без скрытых изменений runtime или permissions.
        agent_id: Точный идентификатор из списка доступных суб-агентов.
    """
    if runtime is None:
        raise ValueError("ToolRuntime is required")
    agent = get_current_agent()
    if agent is None:
        raise RuntimeError("GigaAgent runtime is unavailable")
    resolver = RuntimeResolver.from_config(runtime.config)
    user = resolver.user
    factory = await get_session_factory()
    async with factory() as session:
        definition = await agent.subagent_registry.resolve(
            session,
            user,
            agent_id,
            require_runnable=True,
            cli=get_settings().giga_agent_runtime == "cli",
        )
    if definition is None:
        snapshot = {"agent_id": agent_id, "task": task, "status": "needs_setup"}
        return _tool_result(
            runtime,
            content=f"Суб-агент {agent_id!r} выключен, недоступен или требует настройки.",
            snapshot=snapshot,
            is_error=True,
        )

    configurable = dict((runtime.config or {}).get("configurable") or {})
    parent_metadata = await _parent_metadata(runtime)
    project_id = parent_metadata.get("project_id") or configurable.get("project_id")
    parent_thread_id = configurable.get("thread_id")
    parent_run_id = configurable.get("run_id")
    session_key = _session_key(parent_thread_id, runtime.tool_call_id)
    session_data = await cache.get(session_key)
    if not isinstance(session_data, dict):
        session_data = None

    if session_data is None:
        child_thread_id = str(uuid.uuid4())
        try:
            lease = await acquire_lease(user.id, child_thread_id=child_thread_id)
        except SubagentConcurrencyError as exc:
            return _tool_result(
                runtime,
                content=str(exc),
                snapshot={
                    "agent_id": definition.ref,
                    "task": task,
                    "status": "error",
                    "error_code": exc.code,
                },
                is_error=True,
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
        parent_metadata.get("auto_approve", configurable.get("auto_approve", False))
    )
    parent_plan_mode = bool(getattr(runtime, "state", {}).get("mode") == "plan")
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
    push_ui_message("subagent_activity", snapshot)
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
        if get_settings().giga_agent_runtime == "cli":
            result = await invoke_subgraph_cli(
                agent.graph,
                run_input,
                runtime,
                thread_id=child_thread_id,
                extra_configurable=child_configurable,
            )
        elif not session_data.get("started"):
            metadata = {
                "type": "subagent",
                "subagent": True,
                "agent_id": definition.ref,
                "parent_thread_id": parent_thread_id,
                "parent_run_id": parent_run_id,
                "tool_call_id": runtime.tool_call_id,
                "auto_approve": auto_approve,
                "graph_id": "giga_agent",
            }
            if project_id:
                metadata["project_id"] = str(project_id)
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
                    push_ui_message("subagent_activity", snapshot)
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
        push_ui_message("subagent_activity", snapshot)
        return _tool_result(runtime, content=final, snapshot=snapshot)
    except asyncio.CancelledError:
        snapshot.update(
            {
                "status": "cancelled",
                "finished_at": time.time(),
                "duration": time.time() - started_at,
            }
        )
        push_ui_message("subagent_activity", snapshot)
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
        push_ui_message("subagent_activity", snapshot)
        return _tool_result(
            runtime,
            content=f"Ошибка запуска суб-агента: {exc}",
            snapshot=snapshot,
            is_error=True,
        )
    finally:
        heartbeat_task.cancel()
        await heartbeat_task
        if preserve_session:
            await update_lease(user.id, lease_id, state="interrupted")
        else:
            await cache.delete(session_key)
            await release_lease(user.id, lease_id)
