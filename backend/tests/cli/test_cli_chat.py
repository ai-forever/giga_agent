from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from giga_agent.cli.commands.cli_chat import (
    _CLI_CUSTOM_QUESTION_VALUE,
    _build_cli_question_answer,
    _build_cli_question_choices,
    _build_cli_questions_payload,
    _config_with_cli_turn_flags,
    _extract_interrupt_value,
    _extract_plan_approval_payload,
    _is_cli_context_compaction_turn,
    _is_cli_prompt_mode,
    _latest_context_compaction_result,
    _make_cli_thread_config,
    _next_cli_question_index,
    _normalize_cli_questions,
    _prompt_for_plan_approval_interrupt,
    _prepare_cli_turn,
    _render_cli_question_prompt,
)


def _base_config() -> dict:
    return {
        "configurable": {
            "thread_id": "thread-1",
            "plan_mode": False,
            "context_compaction_only": False,
        }
    }


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


def test_is_cli_prompt_mode_reads_metadata_flag() -> None:
    assert _is_cli_prompt_mode({"metadata": {"cli_prompt_mode": True}})
    assert not _is_cli_prompt_mode({"metadata": {"cli_prompt_mode": False}})
    assert not _is_cli_prompt_mode(None)


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
