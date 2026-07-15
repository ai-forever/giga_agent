from __future__ import annotations

import contextvars
import time
from typing import Any, Awaitable, Callable

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langgraph.runtime import Runtime

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.observability.metrics import (
    LLM_ERRORS,
    LLM_LATENCY,
    LLM_TOKENS,
    RUN_DURATION,
    RUN_MODEL_CALLS,
    TOOL_CALLS,
    TOOL_LATENCY,
    _model_label,
)

# The middleware instance is a shared singleton across concurrent runs, so
# per-run state lives in contextvars (each run executes in its own context copy).
_run_start: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "giga_metrics_run_start", default=None
)
_run_model_calls: contextvars.ContextVar[int] = contextvars.ContextVar(
    "giga_metrics_run_model_calls", default=0
)


def _model_name_from_response(resp: ModelResponse, request: ModelRequest) -> str:
    result = getattr(resp, "result", None) or []
    if result:
        meta = getattr(result[-1], "response_metadata", None) or {}
        name = meta.get("model_name") or meta.get("model")
        if name:
            return _model_label(str(name))
    # Fallback to the model instance's configured id.
    model = getattr(request, "model", None)
    for attr in ("model_name", "model"):
        val = getattr(model, attr, None)
        if isinstance(val, str) and val:
            return _model_label(val)
    return _model_label(None)


def _record_tokens(resp: ModelResponse, model: str) -> None:
    result = getattr(resp, "result", None) or []
    if not result:
        return
    usage = getattr(result[-1], "usage_metadata", None)
    if not usage:
        return
    prompt = usage.get("input_tokens")
    completion = usage.get("output_tokens")
    if prompt:
        LLM_TOKENS.labels(model=model, kind="prompt").inc(prompt)
    if completion:
        LLM_TOKENS.labels(model=model, kind="completion").inc(completion)


class MetricsMiddleware(AgentMiddleware):
    """Record Prometheus metrics for the main agent loop.

    Covers the primary model calls (tokens/latency/errors) and every tool call
    (count/latency/status), plus per-run duration and model-call count (a proxy
    for run length / runaway detection). Only registered when
    ``GIGA_AGENT_METRICS_ENABLED`` is set — see base.py.

    Coverage boundary: this sees the MAIN agent's model calls. Sub-LLM calls made
    via ``get_llm()`` outside this loop (think/memory/thread_title/subagents,
    experimental graph) are not counted here — see docs/observability-plan.md §3.4.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = state, runtime, config
        _run_start.set(time.monotonic())
        _run_model_calls.set(0)
        return None

    async def after_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = state, runtime, config
        start = _run_start.get()
        if start is not None:
            RUN_DURATION.observe(time.monotonic() - start)
        RUN_MODEL_CALLS.observe(_run_model_calls.get())
        return None

    async def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        _run_model_calls.set(_run_model_calls.get() + 1)
        start = time.monotonic()
        try:
            resp = await handler(request)
        except Exception:
            LLM_ERRORS.labels(model=_model_label(None)).inc()
            raise
        model = _model_name_from_response(resp, request)
        LLM_LATENCY.labels(model=model).observe(time.monotonic() - start)
        _record_tokens(resp, model)
        return resp

    async def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        tool_name = (request.tool_call or {}).get("name") or getattr(
            request.tool, "name", "unknown"
        )
        start = time.monotonic()
        try:
            result = await handler(request)
        except Exception:
            TOOL_CALLS.labels(tool=tool_name, status="error").inc()
            TOOL_LATENCY.labels(tool=tool_name).observe(time.monotonic() - start)
            raise
        status = "ok"
        if (
            isinstance(result, ToolMessage)
            and getattr(result, "status", None) == "error"
        ):
            status = "error"
        TOOL_CALLS.labels(tool=tool_name, status=status).inc()
        TOOL_LATENCY.labels(tool=tool_name).observe(time.monotonic() - start)
        return result
