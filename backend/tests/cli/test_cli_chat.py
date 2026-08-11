from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from giga_agent.cli.app import app
from giga_agent.cli.commands.cli_chat import (
    _CLI_CUSTOM_QUESTION_VALUE,
    _ChatState,
    _build_cli_question_answer,
    _build_cli_question_choices,
    _build_cli_questions_payload,
    _config_with_cli_turn_flags,
    _extract_cli_message_event,
    _extract_interrupt_value,
    _extract_plan_approval_payload,
    _extract_subagent_activity_event,
    _handle_subagent_activity,
    _is_cli_context_compaction_turn,
    _is_cli_prompt_mode,
    _latest_context_compaction_result,
    _make_cli_thread_config,
    _next_cli_question_index,
    _normalize_cli_questions,
    _prompt_for_plan_approval_interrupt,
    _prepare_cli_turn,
    _render_cli_question_prompt,
    _stop_subagent_statuses,
    _chat_loop,
)


def _base_config() -> dict:
    return {
        "configurable": {
            "thread_id": "thread-1",
            "plan_mode": False,
            "context_compaction_only": False,
        }
    }


class _FakeStatus:
    instances = []

    def __init__(self, text, *, console, spinner):
        self.text = text
        self.console = console
        self.spinner = spinner
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def update(self, text):
        self.text = text


def test_extract_subagent_activity_from_custom_event() -> None:
    activity = {"tool_call_id": "call-1", "status": "running", "task": "Research"}

    assert _extract_subagent_activity_event(
        (
            "custom",
            {
                "type": "ui",
                "name": "subagent_activity",
                "props": activity,
            },
        )
    ) == activity
    assert _extract_subagent_activity_event(("messages", (object(), {}))) is None


def test_extract_cli_message_event_supports_multi_and_legacy_shapes() -> None:
    message_event = (object(), {"node": "model"})

    assert _extract_cli_message_event(("messages", message_event)) == message_event
    assert _extract_cli_message_event(message_event) == message_event
    assert _extract_cli_message_event(("custom", {})) is None


def test_handle_subagent_activity_starts_and_completes_status(
    monkeypatch,
) -> None:
    from rich.console import Console

    _FakeStatus.instances = []
    monkeypatch.setattr("rich.status.Status", _FakeStatus)
    console = Console(record=True)
    active_statuses = {}
    activity = {
        "tool_call_id": "call-1",
        "agent_name": "Researcher",
        "task": "Find <loader>\nimplementation details",
        "status": "running",
    }

    _handle_subagent_activity(console, active_statuses, activity)

    assert len(active_statuses) == 1
    assert _FakeStatus.instances[0].started
    assert _FakeStatus.instances[0].spinner == "dots"

    _handle_subagent_activity(
        console,
        active_statuses,
        {**activity, "status": "completed"},
    )

    assert active_statuses == {}
    assert _FakeStatus.instances[0].stopped
    assert (
        "✓ Subagent Researcher: Find <loader> implementation details completed"
        in console.export_text()
    )


def test_handle_subagent_activity_error_uses_agent_id_fallback_and_raw_text(
    monkeypatch,
) -> None:
    from rich.console import Console

    _FakeStatus.instances = []
    monkeypatch.setattr("rich.status.Status", _FakeStatus)
    console = Console(record=True)
    active_statuses = {}
    activity = {
        "tool_call_id": "call-2",
        "agent_id": "builtin:researcher",
        "task": "Inspect <tag>",
        "status": "running",
    }

    _handle_subagent_activity(console, active_statuses, activity)
    _handle_subagent_activity(
        console,
        active_statuses,
        {**activity, "status": "error", "error": "<failure>"},
    )

    assert (
        "✗ Subagent builtin:researcher: Inspect <tag> failed: <failure>"
        in console.export_text()
    )


def test_stop_subagent_statuses_cleans_up_multiple_active_loaders(
    monkeypatch,
) -> None:
    from rich.console import Console

    _FakeStatus.instances = []
    monkeypatch.setattr("rich.status.Status", _FakeStatus)
    active_statuses = {}

    for call_id in ("call-1", "call-2"):
        _handle_subagent_activity(
            Console(),
            active_statuses,
            {
                "tool_call_id": call_id,
                "agent_name": call_id,
                "task": "Task",
                "status": "running",
            },
        )

    _stop_subagent_statuses(active_statuses)

    assert active_statuses == {}
    assert all(status.stopped for status in _FakeStatus.instances)


def test_prepare_cli_turn_regular_message_keeps_base_config() -> None:
    base = _base_config()

    prepared = _prepare_cli_turn("hello", cwd=Path.cwd(), base_config=base)

    assert prepared is not None
    assert prepared["config"] is base
    assert prepared["input_msg"]["messages"][0].content == "hello"


def test_prepare_cli_turn_compact_sets_compaction_flag() -> None:
    base = _base_config()

    prepared = _prepare_cli_turn("/compact", cwd=Path.cwd(), base_config=base)

    assert prepared is not None
    assert prepared["input_msg"] == {"messages": []}
    assert prepared["config"]["configurable"]["context_compaction_only"] is True
    assert prepared["config"]["configurable"]["plan_mode"] is False
    assert base["configurable"]["context_compaction_only"] is False


def test_is_cli_context_compaction_turn_reads_flag() -> None:
    assert _is_cli_context_compaction_turn(
        {"configurable": {"context_compaction_only": True}}
    )
    assert not _is_cli_context_compaction_turn(
        {"configurable": {"context_compaction_only": False}}
    )
    assert not _is_cli_context_compaction_turn(None)


def test_is_cli_prompt_mode_reads_metadata_flag(monkeypatch) -> None:
    async def read_metadata(config, _thread_id):
        return (config or {}).get("metadata") or {}

    monkeypatch.setattr(
        "giga_agent.cli.commands.cli_chat.get_thread_metadata", read_metadata
    )
    assert asyncio.run(_is_cli_prompt_mode({"metadata": {"cli_prompt_mode": True}}))
    assert not asyncio.run(
        _is_cli_prompt_mode({"metadata": {"cli_prompt_mode": False}})
    )
    assert not asyncio.run(_is_cli_prompt_mode(None))


def test_prepare_cli_turn_new_returns_new_chat_command() -> None:
    prepared = _prepare_cli_turn("/new", cwd=Path.cwd(), base_config=_base_config())

    assert prepared == {"command": "new_chat"}


def test_prepare_cli_turn_plan_sets_plan_mode_and_passes_remainder() -> None:
    base = _base_config()

    prepared = _prepare_cli_turn(
        "/plan составь план миграции",
        cwd=Path.cwd(),
        base_config=base,
    )

    assert prepared is not None
    assert prepared["config"]["configurable"]["plan_mode"] is True
    assert prepared["config"]["configurable"]["context_compaction_only"] is False
    assert (
        prepared["input_msg"]["messages"][0].content
        == "составь план миграции"
    )
    assert base["configurable"]["plan_mode"] is False


def test_prepare_cli_turn_plan_without_remainder_sets_pending_command() -> None:
    prepared = _prepare_cli_turn("/plan", cwd=Path.cwd(), base_config=_base_config())

    assert prepared == {"command": "plan_pending"}


def test_prepare_cli_turn_uses_pending_plan_mode_for_next_message() -> None:
    base = _base_config()

    prepared = _prepare_cli_turn(
        "следующее сообщение",
        cwd=Path.cwd(),
        base_config=base,
        plan_mode_pending=True,
    )

    assert prepared is not None
    assert prepared["config"]["configurable"]["plan_mode"] is True
    assert prepared["consumes_plan_mode_pending"] is True
    assert prepared["input_msg"]["messages"][0].content == "следующее сообщение"


def test_chat_state_can_start_with_pending_plan_mode() -> None:
    state = _ChatState(approve=False, debug=False, plan_mode_pending=True)

    assert state.plan_mode_pending is True
    state.plan_mode_pending = False
    assert state.plan_mode_pending is False


def test_chat_loop_passes_plan_mode_to_prompt_turn(monkeypatch) -> None:
    prepared_turn = _prepare_cli_turn(
        "task",
        cwd=Path.cwd(),
        base_config=_base_config(),
        plan_mode_pending=True,
    )
    prepare_turn = patch(
        "giga_agent.cli.commands.cli_chat._prepare_cli_turn",
        return_value=prepared_turn,
    )
    stream = AsyncMock()
    console = SimpleNamespace(print=lambda *args, **kwargs: None)

    async def create_resolver(_config):
        return SimpleNamespace(user=SimpleNamespace(id="user-1"))

    monkeypatch.setattr(
        "giga_agent.cli.commands.cli_chat._make_console", lambda: console
    )
    monkeypatch.setattr(
        "giga_agent.core.agent.runtime_resolver.RuntimeResolver.create",
        create_resolver,
    )
    monkeypatch.setattr(
        "giga_agent.cli.commands.cli_chat._stream_and_handle_interrupts", stream
    )

    with prepare_turn as prepare_mock:
        asyncio.run(
            _chat_loop(
                object(),
                object(),
                _ChatState(approve=True, debug=False),
                False,
                Path.cwd(),
                prompt="task",
                plan_mode=True,
            )
        )

    assert prepare_mock.call_args.kwargs["plan_mode_pending"] is True
    stream.assert_awaited_once()


def test_cli_help_mentions_plan_option() -> None:
    result = CliRunner().invoke(app, ["cli", "--help"])

    assert result.exit_code == 0
    assert "--plan" in result.stdout


def test_make_cli_thread_config_sets_thread_and_user() -> None:
    config = _make_cli_thread_config(
        thread_id="thread-2",
        checkpointer=object(),
        user_id="user-1",
    )

    assert config["configurable"]["thread_id"] == "thread-2"
    assert config["configurable"]["langgraph_auth_user"]["identity"] == "user-1"


def test_extract_interrupt_value_reads_payload_from_state() -> None:
    state = SimpleNamespace(
        interrupts=[
            SimpleNamespace(
                value={
                    "type": "questions",
                    "questions": [{"id": "q_0", "text": "Уточнение?"}],
                }
            )
        ]
    )

    assert _extract_interrupt_value(state) == {
        "type": "questions",
        "questions": [{"id": "q_0", "text": "Уточнение?"}],
    }


def test_extract_plan_approval_payload_normalizes_todos() -> None:
    payload = _extract_plan_approval_payload(
        {
            "type": "plan_approval",
            "plan_content": "  # План  ",
            "todos": [
                {"id": "10", "content": "  Первый шаг  ", "note": "  деталь  "},
                {"content": "Второй шаг", "status": "pending"},
                {"id": "x", "content": "   "},
                "skip",
            ],
        }
    )

    assert payload == {
        "plan_content": "# План",
        "todos": [
            {"id": "10", "content": "Первый шаг", "note": "деталь"},
            {"id": "2", "content": "Второй шаг", "status": "pending"},
        ],
    }


def test_build_cli_question_choices_appends_custom_option() -> None:
    choices = _build_cli_question_choices(
        [
            {"id": "q_0_opt_0", "text": "A"},
            {"id": "q_0_opt_1", "text": "B"},
        ]
    )

    assert choices == [
        ("q_0_opt_0", "A"),
        ("q_0_opt_1", "B"),
        (_CLI_CUSTOM_QUESTION_VALUE, "Свой вариант"),
    ]


def test_build_cli_question_answer_accepts_multi_selection_with_custom_text() -> None:
    answer = _build_cli_question_answer(
        "q_0",
        question_type="multi",
        selection=["q_0_opt_0", "q_0_opt_1", _CLI_CUSTOM_QUESTION_VALUE],
        custom_text="другой вариант",
    )

    assert answer == {
        "question_id": "q_0",
        "selected": ["q_0_opt_0", "q_0_opt_1"],
        "other_text": "другой вариант",
    }


def test_build_cli_question_answer_treats_custom_single_choice_as_other_option() -> None:
    answer = _build_cli_question_answer(
        "q_0",
        question_type="single",
        selection=_CLI_CUSTOM_QUESTION_VALUE,
        custom_text="свой ответ",
    )

    assert answer == {
        "question_id": "q_0",
        "selected": [],
        "other_text": "свой ответ",
    }


def test_build_cli_question_answer_rejects_empty_custom_text() -> None:
    answer = _build_cli_question_answer(
        "q_0",
        question_type="single",
        selection=_CLI_CUSTOM_QUESTION_VALUE,
        custom_text="   ",
    )

    assert answer is None


def test_render_cli_question_prompt_marks_current_option_without_green_style() -> None:
    fragments = _render_cli_question_prompt(
        question_number=2,
        total_questions=3,
        question={
            "text": "Выберите вариант",
            "type": "single",
            "choices": [
                ("q_0_opt_0", "A"),
                ("q_0_opt_1", "B"),
                (_CLI_CUSTOM_QUESTION_VALUE, "Свой вариант"),
            ],
        },
        cursor_index=1,
        selected_values=set(),
        custom_text="",
    )

    assert ("class:questions-option.current-number", "2. ") in fragments
    assert ("class:questions-option.current-text", "B") in fragments
    assert not any("Selection:" in text for _, text in fragments)
    assert ("class:questions-option.text", "Свой вариант:") in fragments


def test_normalize_cli_questions_preserves_navigation_data() -> None:
    questions = _normalize_cli_questions(
        [
            {
                "id": "q_0",
                "text": "Первый вопрос",
                "type": "single",
                "options": [{"id": "opt_0", "text": "A"}],
            },
            {
                "id": "q_1",
                "text": "Второй вопрос",
                "type": "multi",
                "options": [{"id": "opt_1", "text": "B"}],
            },
        ]
    )

    assert questions[0]["choices"][-1] == (_CLI_CUSTOM_QUESTION_VALUE, "Свой вариант")
    assert questions[1]["type"] == "multi"


def test_next_cli_question_index_returns_next_unanswered_question() -> None:
    questions = _normalize_cli_questions(
        [
            {
                "id": "q_0",
                "text": "Первый вопрос",
                "type": "single",
                "options": [{"id": "opt_0", "text": "A"}],
            },
            {
                "id": "q_1",
                "text": "Второй вопрос",
                "type": "single",
                "options": [{"id": "opt_1", "text": "B"}],
            },
        ]
    )

    next_index = _next_cli_question_index(
        current_index=0,
        questions=questions,
        selected_by_question=[{"opt_0"}, set()],
        custom_text_by_question=["", ""],
    )

    assert next_index == 1


def test_build_cli_questions_payload_requires_all_answers() -> None:
    questions = _normalize_cli_questions(
        [
            {
                "id": "q_0",
                "text": "Первый вопрос",
                "type": "single",
                "options": [{"id": "opt_0", "text": "A"}],
            },
            {
                "id": "q_1",
                "text": "Второй вопрос",
                "type": "single",
                "options": [{"id": "opt_1", "text": "B"}],
            },
        ]
    )

    payload = _build_cli_questions_payload(
        questions,
        selected_by_question=[{"opt_0"}, set()],
        custom_text_by_question=["", ""],
    )

    assert payload is None


def test_config_with_cli_turn_flags_preserves_noncopyable_objects() -> None:
    lock = threading.Lock()
    base = {
        "configurable": {
            "thread_id": "thread-1",
            "checkpointer": lock,
            "plan_mode": False,
        }
    }

    turn = _config_with_cli_turn_flags(base, context_compaction_only=True)

    assert turn["configurable"]["checkpointer"] is lock
    assert turn["configurable"]["context_compaction_only"] is True
    assert base["configurable"].get("context_compaction_only") is None


def test_prompt_for_plan_approval_interrupt_approves_on_yes() -> None:
    state = SimpleNamespace(approve=False, debug=False)
    console = object()
    approve_session = SimpleNamespace(prompt_async=AsyncMock(return_value="y"))

    with (
        patch(
            "giga_agent.cli.commands.cli_chat._print_plan_approval_card",
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._make_approve_prompt_session",
            return_value=approve_session,
        ),
    ):
        result = asyncio.run(
            _prompt_for_plan_approval_interrupt(
                {
                    "type": "plan_approval",
                    "plan_content": "# План",
                    "todos": [{"id": "1", "content": "Шаг"}],
                },
                console,
                state,
                render_markdown=True,
                auto_approve=False,
            )
        )

    assert result == {"action": "approve"}
    approve_session.prompt_async.assert_awaited_once()


def test_prompt_for_plan_approval_interrupt_ignores_auto_approve_flag() -> None:
    state = SimpleNamespace(approve=True, debug=False)
    console = object()
    approve_session = SimpleNamespace(prompt_async=AsyncMock(return_value="y"))

    with (
        patch(
            "giga_agent.cli.commands.cli_chat._print_plan_approval_card",
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._make_approve_prompt_session",
            return_value=approve_session,
        ),
    ):
        result = asyncio.run(
            _prompt_for_plan_approval_interrupt(
                {
                    "type": "plan_approval",
                    "plan_content": "# План",
                    "todos": [{"id": "1", "content": "Шаг"}],
                },
                console,
                state,
                render_markdown=True,
                auto_approve=False,
            )
        )

    assert result == {"action": "approve"}
    approve_session.prompt_async.assert_awaited_once()


def test_prompt_for_plan_approval_interrupt_auto_approves_in_prompt_mode() -> None:
    state = SimpleNamespace(approve=True, debug=False)
    console = object()
    approve_session = SimpleNamespace(prompt_async=AsyncMock(return_value="y"))

    with (
        patch(
            "giga_agent.cli.commands.cli_chat._print_plan_approval_card",
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._make_approve_prompt_session",
            return_value=approve_session,
        ),
    ):
        result = asyncio.run(
            _prompt_for_plan_approval_interrupt(
                {
                    "type": "plan_approval",
                    "plan_content": "# План",
                    "todos": [{"id": "1", "content": "Шаг"}],
                },
                console,
                state,
                render_markdown=True,
                auto_approve=True,
            )
        )

    assert result == {"action": "approve"}
    approve_session.prompt_async.assert_not_awaited()


def test_prompt_for_plan_approval_interrupt_uses_inline_feedback_as_reject() -> None:
    state = SimpleNamespace(approve=False, debug=False)
    console = object()
    approve_session = SimpleNamespace(
        prompt_async=AsyncMock(return_value="Добавь риски и зависимости")
    )

    with (
        patch(
            "giga_agent.cli.commands.cli_chat._print_plan_approval_card",
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._make_approve_prompt_session",
            return_value=approve_session,
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._prompt_for_question_text_answer",
            new=AsyncMock(),
        ) as feedback_prompt,
    ):
        result = asyncio.run(
            _prompt_for_plan_approval_interrupt(
                {
                    "type": "plan_approval",
                    "plan_content": "# План",
                    "todos": [],
                },
                console,
                state,
                render_markdown=False,
                auto_approve=False,
            )
        )

    assert result == {
        "action": "reject",
        "feedback": "Добавь риски и зависимости",
    }
    feedback_prompt.assert_not_awaited()


def test_prompt_for_plan_approval_interrupt_requests_feedback_after_no() -> None:
    state = SimpleNamespace(approve=False, debug=False)
    console = object()
    approve_session = SimpleNamespace(prompt_async=AsyncMock(return_value="n"))
    feedback_prompt = AsyncMock(return_value="Добавь критерии готовности")

    with (
        patch(
            "giga_agent.cli.commands.cli_chat._print_plan_approval_card",
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._make_approve_prompt_session",
            return_value=approve_session,
        ),
        patch(
            "giga_agent.cli.commands.cli_chat._prompt_for_question_text_answer",
            new=feedback_prompt,
        ),
    ):
        result = asyncio.run(
            _prompt_for_plan_approval_interrupt(
                {
                    "type": "plan_approval",
                    "plan_content": "# План",
                    "todos": [{"id": "1", "content": "Шаг"}],
                },
                console,
                state,
                render_markdown=True,
                auto_approve=False,
            )
        )

    assert result == {
        "action": "reject",
        "feedback": "Добавь критерии готовности",
    }
    feedback_prompt.assert_awaited_once()


def test_latest_context_compaction_result_reads_last_payload() -> None:
    state = SimpleNamespace(
        values={
            "messages": [
                SimpleNamespace(
                    content="old",
                    additional_kwargs={
                        "giga_agent": {
                            "context_compaction": {
                                "version": 1,
                                "status": "started",
                            }
                        }
                    },
                ),
                SimpleNamespace(
                    content="done",
                    additional_kwargs={
                        "giga_agent": {
                            "context_compaction": {
                                "version": 1,
                                "status": "completed",
                            }
                        }
                    },
                ),
            ]
        }
    )

    assert _latest_context_compaction_result(state) == ("completed", "done")
