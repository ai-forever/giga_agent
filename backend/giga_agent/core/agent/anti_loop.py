"""Anti-loop detection for the agent tool-call loop.

The agent runs model -> tools -> model in a loop bounded only by a very high
recursion_limit. A weak model can get stuck: repeating the same call, bouncing
between two tools, grinding through many steps without progress, or retrying a
failing tool forever. These detectors run on the message history at the start of
each model step; if any fires, the caller stops the run with a terminal message.

Detectors (matching the agreed design):
- A: same tool call (name + args) repeated >= DUPLICATE_CALL_THRESHOLD times in
     the current user turn.
- B: an oscillating cycle of tool-call signatures (A->B->A->B...).
- C: too many tool rounds since the last user message (step budget).
- D: a streak of consecutive errored tool results (failing retries).
"""

from __future__ import annotations

import json

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolMessage,
)

# A: identical (name + args) signature seen this many times in the turn.
DUPLICATE_CALL_THRESHOLD = 4
# B: an oscillating block must repeat at least this many times. Kept below
# DUPLICATE_CALL_THRESHOLD so an A->B->A->B cycle is caught before any single
# call hits the duplicate threshold.
OSCILLATION_MIN_REPEATS = 2
# ...and we look for cycles no longer than this many AI steps.
OSCILLATION_MAX_PERIOD = 5
# C: max tool rounds (AI messages with tool calls) since the last user message.
STEP_BUDGET_PER_TURN = 100
# D: consecutive errored tool results before we give up retrying.
ERROR_STREAK_THRESHOLD = 4


def _tool_call_signature(message: AIMessage) -> str | None:
    """Stable signature of an AIMessage's tool calls (name + sorted args).

    Returns None for AI messages without tool calls so plain assistant turns do
    not participate in cycle/duplicate detection.
    """
    if not message.tool_calls:
        return None
    parts: list[str] = []
    for call in message.tool_calls:
        try:
            args = json.dumps(
                call.get("args", {}), sort_keys=True, ensure_ascii=False
            )
        except (TypeError, ValueError):
            args = str(call.get("args", {}))
        parts.append(f"{call.get('name')}::{args}")
    # Sort so a multi-tool batch is order-independent.
    return "|".join(sorted(parts))


def _messages_since_last_human(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Messages after the most recent HumanMessage (the current user turn)."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return list(messages[i + 1 :])
    return list(messages)


def _detect_duplicate(signatures: list[str]) -> str | None:
    """A: the most recent signature appears >= threshold times in the turn."""
    if not signatures:
        return None
    last = signatures[-1]
    count = signatures.count(last)
    if count >= DUPLICATE_CALL_THRESHOLD:
        name = last.split("::", 1)[0]
        return (
            f"повторяет один и тот же вызов '{name}' с теми же аргументами "
            f"{count} раз(а)"
        )
    return None


def _detect_oscillation(signatures: list[str]) -> str | None:
    """B: trailing signatures form a repeating cycle of length 2..MAX_PERIOD."""
    n = len(signatures)
    for period in range(2, OSCILLATION_MAX_PERIOD + 1):
        needed = period * OSCILLATION_MIN_REPEATS
        if n < needed:
            continue
        window = signatures[-needed:]
        block = window[:period]
        # A true oscillation alternates between distinct calls; a block of
        # identical signatures is a duplicate, already covered by detector A.
        if len(set(block)) < 2:
            continue
        if all(window[i] == block[i % period] for i in range(needed)):
            names = " -> ".join(sig.split("::", 1)[0] for sig in block)
            return (
                f"зациклился на повторяющейся последовательности вызовов "
                f"({names}), повторённой {OSCILLATION_MIN_REPEATS}+ раз"
            )
    return None


def _detect_step_budget(signatures: list[str]) -> str | None:
    """C: too many tool rounds since the last user message."""
    rounds = len(signatures)
    if rounds >= STEP_BUDGET_PER_TURN:
        return (
            f"израсходовал бюджет шагов: {rounds} вызовов инструментов "
            f"без завершения задачи (лимит {STEP_BUDGET_PER_TURN})"
        )
    return None


def _detect_error_streak(messages: list[AnyMessage]) -> str | None:
    """D: a streak of consecutive errored tool results at the tail."""
    streak = 0
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            if getattr(message, "status", None) == "error":
                streak += 1
                continue
            # A successful tool result breaks the streak.
            break
        if isinstance(message, AIMessage):
            # AI step between error results is expected; keep scanning.
            continue
        break
    if streak >= ERROR_STREAK_THRESHOLD:
        return (
            f"{streak} вызовов инструментов подряд завершились ошибкой "
            f"(лимит {ERROR_STREAK_THRESHOLD})"
        )
    return None


def detect_loop(messages: list[AnyMessage]) -> str | None:
    """Return a human-readable reason if the agent is looping, else None.

    Detectors are ordered cheapest/most-specific first; the first hit wins.
    """
    turn = _messages_since_last_human(messages)
    signatures = [
        sig
        for m in turn
        if isinstance(m, AIMessage) and (sig := _tool_call_signature(m)) is not None
    ]

    return (
        _detect_duplicate(signatures)
        or _detect_oscillation(signatures)
        or _detect_step_budget(signatures)
        or _detect_error_streak(turn)
    )
