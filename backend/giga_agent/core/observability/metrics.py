"""Prometheus metric definitions for giga_agent.

Metrics are defined at MODULE level (imported once) so re-import never raises
``Duplicated timeseries in CollectorRegistry``. Labels are kept low-cardinality
on purpose — run/thread/user ids belong in logs (Loki), never in metric labels.

Nothing here has any effect unless ``GIGA_AGENT_METRICS_ENABLED`` is set: the
recording helpers are only ever called from code paths guarded by that flag,
and importing this module is cheap (plain counters, no I/O).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- LLM ---------------------------------------------------------------------
LLM_TOKENS = Counter(
    "giga_llm_tokens_total",
    "LLM tokens consumed",
    ["model", "kind"],  # kind = prompt | completion
)
LLM_LATENCY = Histogram(
    "giga_llm_latency_seconds",
    "LLM call latency (seconds)",
    ["model"],
)
LLM_ERRORS = Counter(
    "giga_llm_errors_total",
    "LLM call errors",
    ["model"],
)

# --- Tools -------------------------------------------------------------------
TOOL_CALLS = Counter(
    "giga_tool_calls_total",
    "Tool calls",
    ["tool", "status"],  # status = ok | error
)
TOOL_LATENCY = Histogram(
    "giga_tool_latency_seconds",
    "Tool call latency (seconds)",
    ["tool"],
)

# --- Graph runs --------------------------------------------------------------
RUN_MODEL_CALLS = Histogram(
    "giga_run_model_calls",
    "Model calls per agent run (proxy for run length / runaway detection)",
    buckets=[1, 2, 4, 8, 16, 32, 64, 128, 256],
)
RUN_DURATION = Histogram(
    "giga_run_duration_seconds",
    "Agent run wall-clock duration (seconds)",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
)

# --- Sandboxes ---------------------------------------------------------------
SANDBOX_ACTIVE = Gauge(
    "giga_sandbox_active",
    "Currently active sandboxes",
    ["provider"],
)
SANDBOX_EVENTS = Counter(
    "giga_sandbox_events_total",
    "Sandbox lifecycle events",
    ["provider", "event"],  # event = created | destroyed | orphan_reaped | error
)


def _model_label(name: str | None) -> str:
    """Clamp the model label to a bounded value (avoid unbounded cardinality)."""
    return (name or "unknown").strip() or "unknown"
