"""Tests for the agent anti-loop detectors, focused on detector A (duplicate).

Detector A must fire only on a *consecutive* streak of identical tool calls, so a
healthy edit→check→edit→check workflow that reuses one idempotent verification
command between productive steps is not mistaken for a stuck loop.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from giga_agent.core.agent.anti_loop import (
    DUPLICATE_CALL_THRESHOLD,
    ERROR_STREAK_THRESHOLD,
    STEP_BUDGET_PER_TURN,
    detect_loop,
)


def _ai(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"{name}-{id(args)}"}],
    )


def _ok_tool(name: str) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=name)


def _error_tool(name: str) -> ToolMessage:
    return ToolMessage(content="error", status="error", tool_call_id=name)


def _shell(cmd: str) -> AIMessage:
    return _ai("shell", {"command": cmd, "description": "check"})


def _message_tool(content: str = "status") -> AIMessage:
    return _ai("message", {"content": content, "expect_response": False})


def test_consecutive_duplicates_trigger():
    """N identical calls back-to-back is a real loop -> fire."""
    messages = [HumanMessage(content="go")]
    for _ in range(DUPLICATE_CALL_THRESHOLD):
        messages.append(_shell("wc -c /app/gpt2.c"))
        messages.append(_ok_tool("shell"))
    reason = detect_loop(messages)
    assert reason is not None
    assert "shell" in reason


def test_interleaved_checks_do_not_trigger():
    """edit→wc→edit→wc… reuses the same check but makes progress -> no fire.

    This is the gpt2-codegolf false positive: 4 identical `wc -c` checks spread
    across distinct, productive edit_file calls must NOT be flagged.
    """
    messages: list = [HumanMessage(content="shrink the file")]
    for i in range(DUPLICATE_CALL_THRESHOLD + 1):
        # A genuinely different productive edit each round resets the streak.
        messages.append(_ai("edit_file", {"file_path": "/app/gpt2.c", "find": f"x{i}"}))
        messages.append(_ok_tool("edit_file"))
        messages.append(_shell("wc -c /app/gpt2.c"))
        messages.append(_ok_tool("shell"))
    assert detect_loop(messages) is None


def test_streak_reset_by_intervening_call():
    """Identical calls that are broken up by one different call don't accumulate."""
    messages: list = [HumanMessage(content="go")]
    # 3 identical, then a different call, then 3 identical again: max streak 3 < 4.
    for _ in range(DUPLICATE_CALL_THRESHOLD - 1):
        messages.append(_shell("ls"))
        messages.append(_ok_tool("shell"))
    messages.append(_ai("read_file", {"path": "/app/x"}))
    messages.append(_ok_tool("read_file"))
    for _ in range(DUPLICATE_CALL_THRESHOLD - 1):
        messages.append(_shell("ls"))
        messages.append(_ok_tool("shell"))
    assert detect_loop(messages) is None


def test_message_tool_resets_step_budget():
    """A visible message to the user starts a fresh tool-round budget."""
    messages: list = [HumanMessage(content="go")]
    for i in range(STEP_BUDGET_PER_TURN - 1):
        messages.append(_shell(f"before-{i}"))
        messages.append(_ok_tool("shell"))
    messages.append(_message_tool())
    messages.append(_ok_tool("message"))
    for i in range(STEP_BUDGET_PER_TURN - 1):
        messages.append(_shell(f"after-{i}"))
        messages.append(_ok_tool("shell"))

    assert detect_loop(messages) is None


def test_repeated_message_tool_calls_do_not_trigger_duplicate_loop():
    """Multiple message-tool calls are treated as user-visible progress."""
    messages: list = [HumanMessage(content="go")]
    for _ in range(DUPLICATE_CALL_THRESHOLD):
        messages.append(_message_tool("still working"))
        messages.append(_ok_tool("message"))

    assert detect_loop(messages) is None


def test_message_tool_does_not_reset_error_streak():
    messages: list = [HumanMessage(content="go")]
    for _ in range(ERROR_STREAK_THRESHOLD):
        messages.append(_message_tool("still working"))
        messages.append(_error_tool("message"))

    reason = detect_loop(messages)
    assert reason is not None
    assert "ошибкой" in reason
