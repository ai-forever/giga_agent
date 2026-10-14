from __future__ import annotations

from prompt_toolkit.document import Document

from giga_agent.cli.commands._slash_command_completer import (
    make_slash_command_completer,
)


def _texts(document_text: str) -> list[str]:
    completer = make_slash_command_completer()
    document = Document(text=document_text, cursor_position=len(document_text))
    return [completion.text for completion in completer.get_completions(document, None)]


def test_slash_command_completer_lists_all_commands_for_bare_slash() -> None:
    assert _texts("/") == ["compact", "new", "plan"]


def test_slash_command_completer_filters_by_prefix() -> None:
    assert _texts("/p") == ["plan"]
    assert _texts("/co") == ["compact"]
    assert _texts("/n") == ["new"]


def test_slash_command_completer_ignores_non_command_input() -> None:
    assert _texts("hello") == []
    assert _texts("hello /x") == []
