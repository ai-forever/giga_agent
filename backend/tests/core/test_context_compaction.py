from __future__ import annotations

from typing import ClassVar

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from giga_agent.conf import reset_settings_cache
from giga_agent.core.agent.context_compaction import (
    context_compaction_message_id,
    find_latest_valid_summary,
    prepare_context_compaction,
    project_messages,
    strip_context_summaries,
)

pytestmark = pytest.mark.anyio
KEEP_TOKENS = 420


@pytest.fixture(autouse=True)
def _context_compaction_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGA_AGENT_CONTEXT_COMPACTION_KEEP_TOKENS", str(KEEP_TOKENS))
    reset_settings_cache()
    yield
    reset_settings_cache()


def _history(
    count: int,
    *,
    input_tokens: int | None = 90,
    label: str = "",
) -> list:
    messages = []
    for index in range(count):
        if index % 2 == 0:
            messages.append(
                HumanMessage(
                    id=f"h-{index}",
                    content=f"{label}user {index} " + ("x" * 60),
                )
            )
        else:
            usage = (
                {
                    "input_tokens": input_tokens,
                    "output_tokens": 1,
                    "total_tokens": input_tokens + 1,
                }
                if index == count - 1 and input_tokens is not None
                else None
            )
            messages.append(
                AIMessage(
                    id=f"a-{index}",
                    content=f"{label}assistant {index} " + ("y" * 60),
                    usage_metadata=usage,
                )
            )
    return messages


async def test_automatic_compaction_uses_last_reported_input_tokens() -> None:
    messages = _history(26, input_tokens=90)
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="summary",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            )
        ]
    )

    result = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )

    assert result.marker is not None
    assert result.input_tokens == 90
    assert result.input_tokens_source == "provider"
    assert result.marker.content == "summary"
    assert result.usage_events[0]["usage"]["input_tokens"] == 10
    payload = result.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["operation_id"] is None
    assert payload["context_window"] == 100
    assert isinstance(payload["input_tokens_after"], int)
    assert payload["input_tokens_after"] >= 0
    assert payload["through_message_id"] == messages[payload["compacted_message_count"] - 1].id
    assert payload["signal_token_source"] == "provider"
    assert payload["compacted_message_count"] > 0
    assert (
        count_tokens_approximately(
            result.messages[1:], use_usage_metadata_scaling=False
        )
        <= KEEP_TOKENS
    )


async def test_missing_last_usage_falls_back_to_approximate_count() -> None:
    messages = _history(26, input_tokens=None)
    messages[-3].usage_metadata = {
        "input_tokens": 99,
        "output_tokens": 1,
        "total_tokens": 100,
    }
    auto_model = FakeMessagesListChatModel(responses=[AIMessage(content="unused")])
    auto = await prepare_context_compaction(
        messages,
        model=auto_model,
        context_window=100,
        reason="auto",
    )
    assert auto.marker is not None
    assert auto.input_tokens_source == "approximate"
    assert auto.marker.content == "unused"

    manual_model = FakeMessagesListChatModel(responses=[AIMessage(content="manual")])
    manual = await prepare_context_compaction(
        messages,
        model=manual_model,
        context_window=100,
        reason="manual",
        operation_id="manual-op",
    )
    assert manual.marker is not None
    assert manual.marker.content == "manual"
    assert manual.marker.id == context_compaction_message_id("manual-op")
    payload = manual.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["operation_id"] == "manual-op"
    assert payload["context_window"] == 100


async def test_manual_compaction_compacts_short_history() -> None:
    messages = _history(4, input_tokens=12)
    model = FakeMessagesListChatModel(responses=[AIMessage(content="manual short")])

    result = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="manual",
    )

    assert result.marker is not None
    assert result.marker.content == "manual short"
    assert len(result.messages) == 1
    payload = result.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["reason"] == "manual"
    assert payload["compacted_message_count"] == len(messages)
    assert payload["retained_message_count"] == 0


async def test_manual_compaction_reuses_existing_summary_when_nothing_new_remains() -> None:
    messages = _history(6, input_tokens=12)
    first_model = FakeMessagesListChatModel(responses=[AIMessage(content="first summary")])
    first = await prepare_context_compaction(
        messages,
        model=first_model,
        context_window=100,
        reason="manual",
    )

    assert first.marker is not None
    persisted = [*messages, first.marker]
    second = await prepare_context_compaction(
        persisted,
        model=_FailingModel(responses=[]),
        context_window=100,
        reason="manual",
    )

    assert second.marker is not None
    assert second.marker.content == "first summary"
    payload = second.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["reason"] == "manual"
    assert payload["compacted_message_count"] == len(messages)
    assert payload["retained_message_count"] == 0


async def test_safe_cutoff_keeps_ai_and_tool_results_together() -> None:
    messages = [HumanMessage(id="old", content="old")]
    messages.append(
        AIMessage(
            id="calls",
            content="",
            tool_calls=[{"id": "call-1", "name": "read", "args": {}}],
        )
    )
    messages.append(ToolMessage(id="tool", content="data", tool_call_id="call-1"))
    messages.extend(_history(18, input_tokens=None))
    # The final AI message drives the automatic trigger.
    messages.append(
        AIMessage(
            id="last",
            content="done",
            usage_metadata={"input_tokens": 90, "output_tokens": 1, "total_tokens": 91},
        )
    )
    model = FakeMessagesListChatModel(responses=[AIMessage(content="summary")])

    result = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )

    assert result.marker is not None
    retained_ids = {message.id for message in result.messages[1:]}
    assert {"calls", "tool"}.issubset(retained_ids)


async def test_latest_valid_marker_projects_summary_and_tail() -> None:
    messages = _history(26, input_tokens=90)
    model = FakeMessagesListChatModel(responses=[AIMessage(content="summary")])
    compacted = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )
    assert compacted.marker is not None
    persisted = [*messages, compacted.marker, AIMessage(id="new", content="new")]

    found = find_latest_valid_summary(persisted)
    assert found is not None
    projected = project_messages(persisted)
    assert (
        projected[0].content
        == "<conversation_summary>\nsummary\n</conversation_summary>"
    )
    assert projected[-1].id == "new"
    assert compacted.marker not in strip_context_summaries(persisted)

    messages[0].content = "edited"
    assert find_latest_valid_summary(persisted) is None
    assert project_messages(persisted)[0].id == "h-0"


async def test_incremental_compaction_summarizes_only_new_prefix() -> None:
    messages = _history(26, input_tokens=90)
    first_model = FakeMessagesListChatModel(responses=[AIMessage(content="first")])
    first = await prepare_context_compaction(
        messages,
        model=first_model,
        context_window=100,
        reason="auto",
    )
    assert first.marker is not None

    extended = [*messages, first.marker, *_history(8, input_tokens=90, label="next ")]
    _RecordingModel.calls.clear()
    second_model = _RecordingModel(responses=[AIMessage(content="second")])
    second = await prepare_context_compaction(
        extended,
        model=second_model,
        context_window=100,
        reason="auto",
    )

    assert second.marker is not None
    payload = second.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["compacted_message_count"] > 0
    assert len(_RecordingModel.calls) == 1
    prompt = str(_RecordingModel.calls[0][-1].content)
    assert "## SESSION INTENT" in prompt
    assert "<previous_summary>" in prompt
    assert "first" in prompt
    assert "user 0" not in prompt


class _RecordingModel(FakeMessagesListChatModel):
    calls: ClassVar[list] = []

    async def ainvoke(self, input, config=None, **kwargs):
        self.calls.append(input)
        return await super().ainvoke(input, config=config, **kwargs)


class _FailingModel(FakeMessagesListChatModel):
    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError("summary failed")


async def test_summary_failure_only_blocks_at_hard_ratio() -> None:
    messages = _history(26, input_tokens=90)
    model = _FailingModel(responses=[])

    soft = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )
    assert soft.error is not None
    assert soft.hard_failure is False

    messages[-1].usage_metadata = {
        "input_tokens": 96,
        "output_tokens": 1,
        "total_tokens": 97,
    }
    hard = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )
    assert hard.error is not None
    assert hard.hard_failure is True


async def test_latest_valid_summary_falls_back_to_boundary_index_when_id_is_missing() -> None:
    messages = _history(26, input_tokens=90)
    for message in messages[:10]:
        message.id = None

    model = FakeMessagesListChatModel(responses=[AIMessage(content="summary")])
    compacted = await prepare_context_compaction(
        messages,
        model=model,
        context_window=100,
        reason="auto",
    )

    assert compacted.marker is not None
    payload = compacted.marker.additional_kwargs["giga_agent"]["context_compaction"]
    assert payload["status"] == "completed"
    assert payload["through_message_id"] is None
    assert payload["through_message_index"] == payload["compacted_message_count"] - 1

    persisted = [*messages, compacted.marker, AIMessage(id="new", content="new")]
    found = find_latest_valid_summary(persisted)
    assert found is not None
    assert found[1] == payload["through_message_index"]
