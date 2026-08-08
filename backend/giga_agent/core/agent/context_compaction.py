"""Usage-driven conversation compaction without deleting checkpoint history."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import (
    count_tokens_approximately,
    get_buffer_string,
)

from giga_agent.conf import get_settings

SUMMARY_BATCH_MESSAGES = 40
SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant context from the conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must extract the highest quality/most relevant pieces of information from your conversation history.
This context will then overwrite the conversation history presented below. Because of this, ensure the context you extract is only the most important information to continue working toward your overall goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in this step.
You want to ensure that you don't repeat any actions you've already completed, so the context you extract from the conversation history should be focused on the most important information to your overall goal.

You should structure your summary using the following sections. Each section acts as a checklist - you must populate it with relevant information or explicitly state "None" if there is nothing to report for that section:

## SESSION INTENT

What is the user's primary goal or request? What overall task are you trying to accomplish? This should be concise but complete enough to understand the purpose of the entire session.

## SUMMARY

Extract and record all of the most important context from the conversation history. Include important choices, conclusions, or strategies determined during this conversation. Include the reasoning behind key decisions. Document any rejected options and why they were not pursued.

## ARTIFACTS

What artifacts, files, or resources were created, modified, or accessed during this conversation? For file modifications, list specific file paths and briefly describe the changes made to each. This section prevents silent loss of artifact information.

## NEXT STEPS

What specific tasks remain to be completed to achieve the session intent? What should you do next?

</instructions>

The user will message you with the full message history from which you'll extract context to create a replacement. Carefully read through it all and think deeply about what information is most important to your overall goal and should be saved:

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
Respond ONLY with the extracted context. Do not include any additional information, or text before or after the extracted context.

<messages>
Messages to summarize:
{messages}
</messages>"""


def context_compaction_message_id(operation_id: str) -> str:
    return f"context-compaction-started-{operation_id}"


@dataclass(frozen=True)
class CompactionResult:
    """Messages projected for the model plus an optional persisted marker."""

    messages: list[AnyMessage]
    marker: SystemMessage | None = None
    attempted: bool = False
    input_tokens: int | None = None
    input_tokens_source: Literal["provider", "approximate"] | None = None
    hard_failure: bool = False
    error: Exception | None = None
    usage_events: tuple[dict[str, Any], ...] = ()


def _marker_payload(message: AnyMessage) -> dict[str, Any] | None:
    if not isinstance(message, SystemMessage):
        return None
    kwargs = message.additional_kwargs or {}
    namespace = kwargs.get("giga_agent")
    if not isinstance(namespace, dict):
        return None
    payload = namespace.get("context_compaction")
    return payload if isinstance(payload, dict) else None


def is_context_summary(message: AnyMessage) -> bool:
    return _marker_payload(message) is not None


def strip_context_summaries(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    return [message for message in messages if not is_context_summary(message)]


def _stable_message_payload(message: AnyMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": message.type,
        "id": message.id,
        "content": message.content,
    }
    if isinstance(message, AIMessage):
        payload["tool_calls"] = message.tool_calls
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
        payload["name"] = message.name
    return payload


def _digest(messages: Sequence[AnyMessage]) -> str:
    raw = json.dumps(
        [_stable_message_payload(message) for message in messages],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find_message_index(messages: Sequence[AnyMessage], message_id: str) -> int | None:
    for index, message in enumerate(messages):
        if message.id == message_id:
            return index
    return None


def _resolve_boundary_index(
    messages: Sequence[AnyMessage],
    *,
    message_id: str | None,
    message_index: int | None,
) -> int | None:
    if message_id:
        resolved = _find_message_index(messages, message_id)
        if resolved is not None:
            return resolved
    if isinstance(message_index, int) and 0 <= message_index < len(messages):
        return message_index
    return None


def find_latest_valid_summary(
    messages: Sequence[AnyMessage],
) -> tuple[SystemMessage, int] | None:
    """Return the newest marker whose boundary and source digest are still valid."""
    source = strip_context_summaries(messages)
    for candidate in reversed(messages):
        payload = _marker_payload(candidate)
        if payload is None or not isinstance(candidate, SystemMessage):
            continue
        boundary_id = payload.get("through_message_id")
        boundary_index = payload.get("through_message_index")
        expected_digest = payload.get("source_digest")
        if not isinstance(expected_digest, str):
            continue
        boundary_index = _resolve_boundary_index(
            source,
            message_id=boundary_id if isinstance(boundary_id, str) else None,
            message_index=boundary_index if isinstance(boundary_index, int) else None,
        )
        if boundary_index is None:
            continue
        if _digest(source[: boundary_index + 1]) == expected_digest:
            return candidate, boundary_index
    return None


def _summary_as_human(summary: str) -> HumanMessage:
    return HumanMessage(
        id=str(uuid.uuid4()),
        content=f"<conversation_summary>\n{summary}\n</conversation_summary>"
    )


def project_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Build the model-visible history from the newest valid marker."""
    source = strip_context_summaries(messages)
    found = find_latest_valid_summary(messages)
    if found is None:
        return source
    marker, boundary_index = found
    return [_summary_as_human(str(marker.content)), *source[boundary_index + 1 :]]


def _last_ai_input_tokens(messages: Sequence[AnyMessage]) -> int | None:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        usage = message.usage_metadata
        if not usage:
            return None
        value = usage.get("input_tokens")
        return int(value) if isinstance(value, int) and value >= 0 else None
    return None


def _count_approximate_tokens(
    messages: Sequence[AnyMessage], *, use_usage_metadata_scaling: bool
) -> int:
    return count_tokens_approximately(
        messages,
        use_usage_metadata_scaling=use_usage_metadata_scaling,
    )


def _signal_tokens(
    messages: Sequence[AnyMessage],
) -> tuple[int | None, Literal["provider", "approximate"] | None]:
    provider_tokens = _last_ai_input_tokens(messages)
    if provider_tokens is not None:
        return provider_tokens, "provider"
    if not messages:
        return None, None
    return (
        _count_approximate_tokens(messages, use_usage_metadata_scaling=True),
        "approximate",
    )


def _find_safe_cutoff_point(messages: Sequence[AnyMessage], cutoff: int) -> int:
    """Return a retained-start index without splitting an AI/tool batch."""
    if cutoff >= len(messages) or not isinstance(messages[cutoff], ToolMessage):
        return cutoff
    tool_ids: set[str] = set()
    index = cutoff
    while index < len(messages) and isinstance(messages[index], ToolMessage):
        tool_id = messages[index].tool_call_id
        if tool_id:
            tool_ids.add(tool_id)
        index += 1

    for candidate in range(cutoff - 1, -1, -1):
        message = messages[candidate]
        if not isinstance(message, AIMessage):
            continue
        ai_ids = {call.get("id") for call in message.tool_calls if call.get("id")}
        if ai_ids & tool_ids:
            return candidate
    return index


def _find_token_based_cutoff(messages: Sequence[AnyMessage], keep_tokens: int) -> int:
    """Find retained-start index using approximate token count for the suffix."""
    if not messages:
        return 0
    if keep_tokens <= 0:
        return 0
    if (
        _count_approximate_tokens(messages, use_usage_metadata_scaling=False)
        <= keep_tokens
    ):
        return 0

    left, right = 0, len(messages)
    cutoff_candidate = len(messages)
    max_iterations = len(messages).bit_length() + 1
    for _ in range(max_iterations):
        if left >= right:
            break
        middle = (left + right) // 2
        suffix_tokens = _count_approximate_tokens(
            messages[middle:],
            use_usage_metadata_scaling=False,
        )
        if suffix_tokens <= keep_tokens:
            cutoff_candidate = middle
            right = middle
        else:
            left = middle + 1

    if cutoff_candidate == len(messages):
        cutoff_candidate = left
    if cutoff_candidate >= len(messages):
        if len(messages) == 1:
            return 0
        cutoff_candidate = len(messages) - 1
    return _find_safe_cutoff_point(messages, cutoff_candidate)


def _format_summary_messages(
    previous_summary: str,
    messages: Sequence[AnyMessage],
) -> str:
    formatted_messages = get_buffer_string(list(messages), format="xml")
    if previous_summary.strip():
        formatted_messages = (
            f"<previous_summary>\n{previous_summary.strip()}\n</previous_summary>\n\n"
            f"{formatted_messages}"
        )
    return SUMMARY_PROMPT.format(messages=formatted_messages).rstrip()


async def _summarize_batch(
    model: BaseChatModel,
    previous_summary: str,
    messages: Sequence[AnyMessage],
    *,
    max_tokens: int,
) -> tuple[str, list[dict[str, Any]]]:
    prompt = _format_summary_messages(previous_summary, messages)
    bound = model.bind(max_tokens=max_tokens).with_config(tags=["nostream"])
    try:
        response = await bound.ainvoke(
            [HumanMessage(content=prompt)],
            config={"metadata": {"lc_source": "context_compaction"}},
        )
    except Exception:
        if len(messages) <= 1:
            raise
        middle = len(messages) // 2
        first, first_usage = await _summarize_batch(
            model,
            previous_summary,
            messages[:middle],
            max_tokens=max_tokens,
        )
        second, second_usage = await _summarize_batch(
            model,
            first,
            messages[middle:],
            max_tokens=max_tokens,
        )
        return second, [*first_usage, *second_usage]
    text = getattr(response, "text", None)
    if not isinstance(text, str):
        text = str(response.content)
    usage = getattr(response, "usage_metadata", None)
    metadata = getattr(response, "response_metadata", None) or {}
    if not usage:
        return text.strip(), []
    event = {
        "model": metadata.get("model_name") or metadata.get("model"),
        "usage": dict(usage),
    }
    return text.strip(), [event]


async def _summarize_messages(
    model: BaseChatModel,
    previous_summary: str,
    messages: Sequence[AnyMessage],
    *,
    max_tokens: int,
) -> tuple[str, list[dict[str, Any]]]:
    summary = previous_summary
    usage_events: list[dict[str, Any]] = []
    for start in range(0, len(messages), SUMMARY_BATCH_MESSAGES):
        summary, batch_usage = await _summarize_batch(
            model,
            summary,
            messages[start : start + SUMMARY_BATCH_MESSAGES],
            max_tokens=max_tokens,
        )
        usage_events.extend(batch_usage)
    return summary, usage_events


async def prepare_context_compaction(
    messages: Sequence[AnyMessage],
    *,
    model: BaseChatModel,
    context_window: int,
    reason: Literal["auto", "manual"] = "auto",
    operation_id: str | None = None,
) -> CompactionResult:
    """Compact if usage crosses the threshold, or unconditionally for manual mode."""
    settings = get_settings()
    current_projection = project_messages(messages)
    source = strip_context_summaries(messages)
    input_tokens, input_tokens_source = _signal_tokens(current_projection)
    force = reason == "manual"

    if not force:
        if not settings.giga_agent_context_compaction_enabled:
            return CompactionResult(messages=current_projection)
        if input_tokens is None:
            return CompactionResult(messages=current_projection)
        ratio = input_tokens / max(1, context_window)
        if ratio < settings.giga_agent_context_compaction_trigger_ratio:
            return CompactionResult(
                messages=current_projection,
                input_tokens=input_tokens,
                input_tokens_source=input_tokens_source,
            )
    else:
        ratio = 0.0

    cutoff = _find_token_based_cutoff(
        source, settings.giga_agent_context_compaction_keep_tokens
    )
    found = find_latest_valid_summary(messages)
    previous_summary = found[0].content if found is not None else ""
    previous_boundary = found[1] if found is not None else -1
    if force and source and cutoff <= previous_boundary + 1:
        # Manual `/compact` should still produce a persisted summary even when
        # the current visible history is already below the automatic keep limit.
        cutoff = len(source)
    elif cutoff <= previous_boundary + 1:
        return CompactionResult(
            messages=current_projection,
            attempted=True,
            input_tokens=input_tokens,
            input_tokens_source=input_tokens_source,
            hard_failure=(
                not force and ratio >= settings.giga_agent_context_compaction_hard_ratio
            ),
        )

    delta = source[previous_boundary + 1 : cutoff]
    if not delta:
        if not force or not previous_summary:
            return CompactionResult(
                messages=current_projection,
                attempted=True,
                input_tokens=input_tokens,
                input_tokens_source=input_tokens_source,
            )
        summary = str(previous_summary)
        usage_events = []
    else:
        try:
            summary, usage_events = await _summarize_messages(
                model,
                str(previous_summary),
                delta,
                max_tokens=settings.giga_agent_context_compaction_summary_max_tokens,
            )
        except Exception as exc:
            if force:
                raise
            return CompactionResult(
                messages=current_projection,
                attempted=True,
                input_tokens=input_tokens,
                input_tokens_source=input_tokens_source,
                hard_failure=ratio >= settings.giga_agent_context_compaction_hard_ratio,
                error=exc,
            )

    boundary = source[cutoff - 1]
    projected = [_summary_as_human(summary), *source[cutoff:]]
    input_tokens_after = _count_approximate_tokens(
        projected, use_usage_metadata_scaling=False
    )
    marker = SystemMessage(
        id=(
            context_compaction_message_id(operation_id)
            if operation_id
            else str(uuid.uuid4())
        ),
        name="context_compaction",
        content=summary,
        additional_kwargs={
            "giga_agent": {
                "context_compaction": {
                    "version": 1,
                    "status": "completed",
                    "operation_id": operation_id,
                    "through_message_id": boundary.id,
                    "through_message_index": cutoff - 1,
                    "source_digest": _digest(source[:cutoff]),
                    "reason": reason,
                    "input_tokens_before": input_tokens,
                    "input_tokens_after": input_tokens_after,
                    "context_window": context_window,
                    "signal_token_count_before": input_tokens,
                    "signal_token_source": input_tokens_source,
                    "compacted_message_count": cutoff,
                    "retained_message_count": len(source) - cutoff,
                }
            }
        },
    )
    return CompactionResult(
        messages=projected,
        marker=marker,
        attempted=True,
        input_tokens=input_tokens,
        input_tokens_source=input_tokens_source,
        usage_events=tuple(usage_events),
    )


__all__ = [
    "CompactionResult",
    "find_latest_valid_summary",
    "context_compaction_message_id",
    "is_context_summary",
    "prepare_context_compaction",
    "project_messages",
    "strip_context_summaries",
]
