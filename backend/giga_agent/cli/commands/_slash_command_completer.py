from __future__ import annotations

import re
from dataclasses import dataclass

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

_SLASH_TOKEN_RE = re.compile(r"(?:^|\s)/([^\s]*)$")


@dataclass(frozen=True)
class SlashCommandSpec:
    name: str
    description: str


_SLASH_COMMANDS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec(
        name="compact",
        description="compact conversation context without sending a user message",
    ),
    SlashCommandSpec(
        name="new",
        description="start a new chat with a fresh thread id",
    ),
    SlashCommandSpec(
        name="plan",
        description="enter planning mode or send a planning request",
    ),
)


class SlashCommandCompleter(Completer):
    def get_completions(self, document: Document, complete_event):
        text_before = document.text_before_cursor
        match = _SLASH_TOKEN_RE.search(text_before)
        if not match:
            return

        query = match.group(1)
        start_position = -len(query)
        query_lower = query.lower()

        for spec in _SLASH_COMMANDS:
            if query_lower and not spec.name.startswith(query_lower):
                continue
            yield Completion(
                text=spec.name,
                start_position=start_position,
                display=[
                    ("class:slash-command.symbol", "/"),
                    ("class:slash-command.name", spec.name),
                    ("class:slash-command.desc", f" — {spec.description}"),
                ],
            )


def make_slash_command_completer() -> Completer:
    return SlashCommandCompleter()
