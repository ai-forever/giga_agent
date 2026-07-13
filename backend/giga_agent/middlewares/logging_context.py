from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

_BOUND_KEYS = ("thread_id", "run_id", "user_id")


def _resolve_thread_id(config: RunnableConfig | dict[str, Any]) -> str | None:
    metadata = config.get("metadata") or {}
    thread_id = metadata.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")
    return None


def _resolve_run_id(config: RunnableConfig | dict[str, Any]) -> str | None:
    metadata = config.get("metadata") or {}
    run_id = metadata.get("run_id") or (config.get("configurable") or {}).get("run_id")
    if run_id:
        return str(run_id)
    return None


def _resolve_user_id(config: RunnableConfig | dict[str, Any]) -> str | None:
    try:
        user_id = get_user_id_from_config(config)
    except Exception:
        return None
    return str(user_id) if user_id else None


class LoggingContextMiddleware(AgentMiddleware):
    """Bind run identifiers into structlog contextvars for the whole agent run.

    Every log record emitted during the run (any logger, any module) then carries
    ``thread_id`` / ``run_id`` / ``user_id`` — so Loki can filter logs by a single
    run without threading these ids through every call site. Cleared in
    ``after_agent`` so ids never leak into an unrelated run reusing the context.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = state, runtime
        bindings: dict[str, str] = {}
        thread_id = _resolve_thread_id(config)
        if thread_id:
            bindings["thread_id"] = thread_id
        run_id = _resolve_run_id(config)
        if run_id:
            bindings["run_id"] = run_id
        user_id = _resolve_user_id(config)
        if user_id:
            bindings["user_id"] = user_id
        if bindings:
            structlog.contextvars.bind_contextvars(**bindings)
        return None

    async def after_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = state, runtime, config
        structlog.contextvars.unbind_contextvars(*_BOUND_KEYS)
        return None
