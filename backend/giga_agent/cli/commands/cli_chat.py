from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from uuid import uuid4

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.logging import setup_cli_logging
from giga_agent.core.process_supervisor import get_process_supervisor
from giga_agent.utils.thread_metadata import (
    get_thread_id_from_config,
    get_thread_metadata,
)

from ..types import LogLevel
from ..utils.dotenv import load_dev_env
from ..utils.secret_key import ensure_dev_secret_key_env

_ATTACHMENT_MARKDOWN_RE = re.compile(r"(!?)\[([^\]]*)\]\(attachment:([^\s)]+)\)")
_BARE_ATTACHMENT_RE = re.compile(r"attachment:([^\s)]+)")
_INCOMPLETE_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*(?:\]\([^)]*)?$")
_INCOMPLETE_ATTACHMENT_RE = re.compile(r"attachment:[^\s)]*$")
_AT_FILE_REF_RE = re.compile(r"(^|\s)@(\S+)")


def _expand_at_file_refs(text: str, cwd: Path) -> str:
    """Rewrite `@<path>` tokens in `text` to `@<absolute-path>`.

    Supports an optional trailing `#<suffix>` (e.g. `@foo.py#42` or
    `@foo.py#10-20`) — the suffix is preserved verbatim in the output.
    Tokens that don't resolve to an existing file or directory are left
    untouched.
    """

    def replace(match: re.Match[str]) -> str:
        prefix, token = match.group(1), match.group(2)
        path_part, sep, suffix = token.partition("#")
        if not path_part:
            return match.group(0)
        path_obj = Path(path_part).expanduser()
        if not path_obj.is_absolute():
            path_obj = cwd / path_obj
        try:
            resolved = path_obj.resolve()
        except OSError:
            return match.group(0)
        if not resolved.exists():
            return match.group(0)
        tail = f"{sep}{suffix}" if sep else ""
        return f"{prefix}@{resolved}{tail}"

    return _AT_FILE_REF_RE.sub(replace, text)


def _config_with_cli_turn_flags(
    config: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    turn_config = dict(config)
    configurable = dict(turn_config.get("configurable") or {})
    configurable.update(overrides)
    turn_config["configurable"] = configurable
    return turn_config


def _make_cli_thread_config(
    *, thread_id: str, checkpointer, user_id: str, no_python_tool: bool = False
) -> dict[str, Any]:
    from langgraph.constants import CONFIG_KEY_CHECKPOINTER

    return {
        "configurable": {
            "thread_id": thread_id,
            CONFIG_KEY_CHECKPOINTER: checkpointer,
            "langgraph_auth_user": {"identity": user_id, "token": ""},
            "no_python_tool": no_python_tool,
        }
    }


def _prepare_cli_turn(
    raw_input: str,
    *,
    cwd: Path,
    base_config: dict[str, Any],
    plan_mode_pending: bool = False,
    auto_approve: bool | None = None,
):
    from langchain_core.messages import HumanMessage

    if auto_approve is not None:
        base_config = _config_with_cli_turn_flags(
            base_config,
            auto_approve=auto_approve,
        )

    text = raw_input.strip()
    if text == "/compact":
        return {
            "input_msg": {"messages": []},
            "config": _config_with_cli_turn_flags(
                base_config,
                context_compaction_only=True,
            ),
        }

    if text == "/new":
        return {"command": "new_chat"}

    if text.startswith("/plan"):
        remainder = text[len("/plan") :].strip()
        if not remainder:
            return {"command": "plan_pending"}
        return {
            "input_msg": {
                "messages": [
                    HumanMessage(
                        id=str(uuid4()),
                        content=_expand_at_file_refs(remainder, cwd),
                    )
                ]
            },
            "config": _config_with_cli_turn_flags(base_config, plan_mode=True),
            "consumes_plan_mode_pending": False,
        }

    return {
        "input_msg": {
            "messages": [
                HumanMessage(
                    id=str(uuid4()),
                    content=_expand_at_file_refs(raw_input, cwd),
                )
            ]
        },
        "config": (
            _config_with_cli_turn_flags(base_config, plan_mode=True)
            if plan_mode_pending
            else base_config
        ),
        "consumes_plan_mode_pending": plan_mode_pending,
    }


def _is_cli_context_compaction_turn(config: dict[str, Any] | None) -> bool:
    configurable = (config or {}).get("configurable") or {}
    return configurable.get("context_compaction_only") is True


async def _is_cli_prompt_mode(config: dict[str, Any] | None) -> bool:
    metadata = await get_thread_metadata(config, get_thread_id_from_config(config))
    return metadata.get("cli_prompt_mode") is True


def _make_console():
    from rich.console import Console
    from rich.theme import Theme

    return Console(
        theme=Theme(
            {
                "markdown.link": "bold underline cyan",
                "markdown.link_url": "bold underline cyan",
            }
        )
    )


class _ChatState:
    __slots__ = (
        "approve",
        "debug",
        "plan_mode_pending",
        "subagent_statuses",
        "displayed_tool_call_ids",
        "pending_tool_call_chunks",
    )

    def __init__(
        self,
        approve: bool,
        debug: bool,
        plan_mode_pending: bool = False,
    ) -> None:
        self.approve = approve
        self.debug = debug
        self.plan_mode_pending = plan_mode_pending
        self.subagent_statuses = {}
        self.displayed_tool_call_ids: set[str] = set()
        self.pending_tool_call_chunks: dict[str, dict[str, Any]] = {}


def _make_toggle_keybindings(state: _ChatState):
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("s-tab")
    def _toggle_approve(event) -> None:
        state.approve = not state.approve

    @kb.add("c-o")
    def _toggle_debug(event) -> None:
        state.debug = not state.debug

    return kb


def _make_bottom_toolbar(state: _ChatState):
    def render():
        if not state.approve and not state.debug:
            return None
        parts: list[tuple[str, str]] = [("class:bottom-toolbar", " ")]
        if state.approve:
            parts.extend(
                [
                    ("class:bottom-toolbar", "auto-approve: "),
                    ("class:bottom-toolbar.value", "on"),
                    ("class:bottom-toolbar", " (shift+tab)"),
                ]
            )
        if state.approve and state.debug:
            parts.append(("class:bottom-toolbar", "   "))
        if state.debug:
            parts.extend(
                [
                    ("class:bottom-toolbar", "debug: "),
                    ("class:bottom-toolbar.value", "on"),
                    ("class:bottom-toolbar", " (ctrl+o)"),
                ]
            )
        parts.append(("class:bottom-toolbar", " "))
        return parts

    return render


_BOTTOM_TOOLBAR_STYLE = {
    "bottom-toolbar": "fg:ansibrightblack bg:default noreverse",
    "bottom-toolbar.text": "fg:ansibrightblack bg:default noreverse",
    "bottom-toolbar.value": "fg:ansibrightcyan bg:default bold noreverse",
}
_CLI_COMPLETION_MENU_RESERVED_LINES = 4
_CLI_CUSTOM_QUESTION_VALUE = "__cli_custom_answer__"


def _make_message_prompt_session(cwd: Path, state: _ChatState):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import merge_completers
    from prompt_toolkit.filters import completion_is_selected, has_completions
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.styles import Style

    from ._at_file_completer import make_at_file_completer
    from ._slash_command_completer import make_slash_command_completer

    kb = KeyBindings()

    @kb.add("down", filter=has_completions)
    def _at_file_next(event) -> None:
        state = event.current_buffer.complete_state
        if not state or not state.completions:
            return
        total = len(state.completions)
        state.complete_index = (
            0 if state.complete_index is None else (state.complete_index + 1) % total
        )

    @kb.add("up", filter=has_completions)
    def _at_file_prev(event) -> None:
        state = event.current_buffer.complete_state
        if not state or not state.completions:
            return
        total = len(state.completions)
        state.complete_index = (
            total - 1
            if state.complete_index is None
            else (state.complete_index - 1) % total
        )

    @kb.add("tab", filter=has_completions)
    def _at_file_tab(event) -> None:
        state = event.current_buffer.complete_state
        if not state or not state.completions:
            return
        total = len(state.completions)
        state.complete_index = (
            0 if state.complete_index is None else (state.complete_index + 1) % total
        )

    @kb.add("enter", filter=completion_is_selected)
    def _at_file_accept(event) -> None:
        buffer = event.current_buffer
        state = buffer.complete_state
        if state and state.current_completion is not None:
            buffer.apply_completion(state.current_completion)
        buffer.complete_state = None

    @kb.add("escape", filter=has_completions, eager=True)
    def _at_file_dismiss(event) -> None:
        event.current_buffer.complete_state = None

    style = Style.from_dict(
        {
            "message-prompt": "ansiblue bold",
            "completion-menu": "bg:default",
            "completion-menu.completion": "bg:default fg:ansicyan",
            "completion-menu.completion.current": "bg:default fg:ansibrightcyan bold",
            "at-file.symbol": "fg:ansibrightmagenta nobold",
            "at-file.path": "fg:ansicyan",
            "slash-command.symbol": "fg:ansibrightyellow bold",
            "slash-command.name": "fg:ansibrightyellow bold",
            "slash-command.desc": "fg:ansibrightblack",
            "completion-menu.completion.current at-file.symbol": "fg:ansibrightmagenta nobold",
            "completion-menu.completion.current at-file.path": "fg:ansibrightcyan bold",
            "completion-menu.completion.current slash-command.symbol": "fg:ansibrightyellow bold",
            "completion-menu.completion.current slash-command.name": "fg:ansibrightyellow bold",
            "completion-menu.completion.current slash-command.desc": "fg:ansibrightblack",
            "scrollbar.background": "bg:default",
            "scrollbar.button": "bg:ansibrightblack",
            **_BOTTOM_TOOLBAR_STYLE,
        }
    )

    return PromptSession(
        message=[("class:message-prompt", "You: ")],
        mouse_support=False,
        style=style,
        completer=merge_completers(
            [
                make_slash_command_completer(),
                make_at_file_completer(cwd),
            ]
        ),
        complete_while_typing=True,
        key_bindings=merge_key_bindings([kb, _make_toggle_keybindings(state)]),
        bottom_toolbar=_make_bottom_toolbar(state),
        reserve_space_for_menu=_CLI_COMPLETION_MENU_RESERVED_LINES,
    )


def _make_approve_prompt_session(
    state: _ChatState,
    *,
    prompt_text: str = "Approve? [Y/n]: ",
):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style

    return PromptSession(
        message=[("class:approve-prompt", prompt_text)],
        mouse_support=False,
        style=Style.from_dict({"approve-prompt": "bold", **_BOTTOM_TOOLBAR_STYLE}),
        key_bindings=_make_toggle_keybindings(state),
        bottom_toolbar=_make_bottom_toolbar(state),
        reserve_space_for_menu=0,
    )


def _make_questions_prompt_session(
    state: _ChatState,
    *,
    prompt_text: str = "Answer: ",
):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style

    return PromptSession(
        message=[("class:questions-prompt", prompt_text)],
        mouse_support=False,
        style=Style.from_dict({"questions-prompt": "bold", **_BOTTOM_TOOLBAR_STYLE}),
        key_bindings=_make_toggle_keybindings(state),
        bottom_toolbar=_make_bottom_toolbar(state),
        reserve_space_for_menu=0,
    )


def _make_questions_choice_style():
    from prompt_toolkit.styles import Style

    return Style.from_dict(
        {
            "questions-title": "bold",
            "questions-help": "fg:ansibrightblack",
            "questions-option.number": "fg:ansibrightblack",
            "questions-option.text": "",
            "questions-option.current-number": "fg:ansicyan bold",
            "questions-option.current-text": "fg:ansicyan bold",
            "questions-option.mark": "fg:ansibrightblack",
            "questions-error": "fg:ansired bold",
            **_BOTTOM_TOOLBAR_STYLE,
        }
    )


def _markdown(markup: str):
    from markdown_it import MarkdownIt
    from rich.markdown import Markdown

    parser = MarkdownIt().enable("strikethrough").enable("table")
    default_validate_link = parser.validateLink

    def validate_link(url: str) -> bool:
        return url.lower().startswith("file://") or default_validate_link(url)

    parser.validateLink = validate_link

    markdown = Markdown(markup)
    markdown.parsed = parser.parse(markup)
    return markdown


def _print_input_encoding_error(console, error: UnicodeDecodeError) -> None:
    console.print(
        "\n[red]Could not decode terminal input as UTF-8.[/red] "
        "[dim]Check your terminal encoding or run with "
        "PYTHONIOENCODING=utf-8 LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8.[/dim]"
    )
    console.print(f"[dim]{error}[/dim]")


def _attachment_link_target(path: str) -> str:
    cleaned = path.strip()
    if "://" in cleaned:
        return cleaned
    path_obj = Path(cleaned).expanduser()
    if path_obj.is_absolute() and path_obj.is_file():
        return f"file://{quote(str(path_obj), safe='/')}"
    return cleaned


def _is_apple_terminal() -> bool:
    return os.environ.get("TERM_PROGRAM") == "Apple_Terminal"


def _attachment_markdown_link(label: str, path: str) -> str:
    target = _attachment_link_target(path)
    fallback_label = label.strip() or Path(path).name or "attachment"
    link_text = (
        target
        if _is_apple_terminal() and target.startswith("file://")
        else f"[link] {fallback_label}"
    )
    return f"[{link_text}]({target})"


def _format_attachment_links(text: str) -> str:
    def replace_markdown(match: re.Match[str]) -> str:
        label = match.group(2).strip()
        attachment_path = match.group(3).strip()
        return _attachment_markdown_link(label, attachment_path)

    rewritten = _ATTACHMENT_MARKDOWN_RE.sub(replace_markdown, text)

    def replace_bare(match: re.Match[str]) -> str:
        attachment_path = match.group(1).strip()
        return _attachment_markdown_link(Path(attachment_path).name, attachment_path)

    rewritten = _BARE_ATTACHMENT_RE.sub(replace_bare, rewritten)
    return re.sub(r"[ \t]+\n", "\n", rewritten).strip()


def _format_text_with_attachments(text: str) -> str:
    return _format_attachment_links(text)


def _safe_stop_live(live) -> None:
    try:
        live.stop()
    except Exception:
        pass


def _has_incomplete_stream_markup(text: str) -> bool:
    return bool(
        _INCOMPLETE_MARKDOWN_LINK_RE.search(text)
        or _INCOMPLETE_ATTACHMENT_RE.search(text)
    )


def _pop_committable_markdown_chunks(buffer: str) -> tuple[list[str], str]:
    chunks: list[str] = []
    in_fence = False
    fence_marker = ""
    block_start = 0
    cursor = 0

    for line in buffer.splitlines(keepends=True):
        line_end = cursor + len(line)
        stripped = line.strip()

        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if in_fence and marker == fence_marker:
                in_fence = False
                fence_marker = ""
            elif not in_fence:
                in_fence = True
                fence_marker = marker

        if line.endswith(("\n", "\r")) and not in_fence and not stripped:
            chunk = buffer[block_start:line_end]
            if chunk.strip() and not _has_incomplete_stream_markup(chunk):
                chunks.append(chunk)
                block_start = line_end

        cursor = line_end

    remainder = buffer[block_start:]
    if in_fence or _has_incomplete_stream_markup(remainder):
        return chunks, remainder

    return chunks, remainder


def _merge_stream_content(collected_text: str, content: str) -> tuple[str, str]:
    """Return updated full text and only the new delta to print."""
    if not content:
        return collected_text, ""
    if collected_text and content.startswith(collected_text):
        return content, content[len(collected_text) :]
    return collected_text + content, content


def _extract_subagent_activity_event(event) -> dict[str, Any] | None:
    if not isinstance(event, tuple) or len(event) != 2 or event[0] != "custom":
        return None
    payload = event[1]
    if not isinstance(payload, dict) or payload.get("name") != "subagent_activity":
        return None
    props = payload.get("props")
    return dict(props) if isinstance(props, dict) else None


def _extract_cli_message_event(event) -> tuple[Any, Any] | None:
    if not isinstance(event, tuple) or len(event) != 2:
        return None
    if event[0] == "messages":
        message_event = event[1]
        return message_event if isinstance(message_event, tuple) else None
    if isinstance(event[0], str):
        return None
    return event


def _extract_cli_update_tool_calls(event) -> list[dict[str, Any]]:
    if not isinstance(event, tuple) or len(event) != 2 or event[0] != "updates":
        return []
    updates = event[1]
    if not isinstance(updates, dict):
        return []

    tool_calls: list[dict[str, Any]] = []
    for node_update in updates.values():
        if not isinstance(node_update, dict):
            continue
        messages = node_update.get("messages") or []
        if not isinstance(messages, (list, tuple)):
            continue
        for message in messages:
            calls = getattr(message, "tool_calls", None) or []
            tool_calls.extend(
                call for call in calls if isinstance(call, dict) and call.get("name")
            )
    return tool_calls


def _is_subagent_message_event(metadata: Any) -> bool:
    return (
        isinstance(metadata, dict)
        and metadata.get("giga_agent_scope") == "subagent"
    )


def _subagent_activity_key(activity: dict[str, Any]) -> str:
    for field in ("tool_call_id", "child_thread_id"):
        value = activity.get(field)
        if value:
            return str(value)
    return f"{activity.get('agent_id', 'subagent')}:{activity.get('task', '')}"


def _subagent_activity_label(activity: dict[str, Any]) -> tuple[str, str]:
    name = _single_line_preview(
        str(activity.get("agent_name") or activity.get("agent_id") or "unknown"),
        max_len=60,
    )
    task = _single_line_preview(str(activity.get("task") or ""), max_len=120)
    return name, task


def _safe_stop_status(status) -> None:
    try:
        status.stop()
    except Exception:
        pass


def _handle_subagent_activity(
    console,
    active_statuses: dict[str, Any],
    activity: dict[str, Any],
) -> None:
    from rich.status import Status
    from rich.text import Text

    status = str(activity.get("status") or "")
    key = _subagent_activity_key(activity)
    name, task = _subagent_activity_label(activity)
    label = f"Subagent {name}: {task}"

    if status == "running":
        active_status = active_statuses.get(key)
        if active_status is None:
            active_status = Status(
                Text(label, style="cyan"),
                console=console,
                spinner="dots",
            )
            active_statuses[key] = active_status
            active_status.start()
        else:
            active_status.update(Text(label, style="cyan"))
        return

    if status not in {"completed", "error", "failed", "timeout", "cancelled"}:
        return

    active_status = active_statuses.pop(key, None)
    if active_status is not None:
        _safe_stop_status(active_status)

    if status == "completed":
        console.print(Text(f"✓ {label} completed", style="green"))
        return

    error = _single_line_preview(
        str(activity.get("error") or "unknown error"), max_len=160
    )
    console.print(Text(f"✗ {label} failed: {error}", style="red"))


def _stop_subagent_statuses(active_statuses: dict[str, Any]) -> None:
    for status in active_statuses.values():
        _safe_stop_status(status)
    active_statuses.clear()


def _load_and_validate_config_file(path: Path) -> str:
    """Read a CLI runtime config JSON file, validate it, and return its raw text."""
    from pydantic import ValidationError

    from giga_agent.core.agent.cli_conf import read_and_validate_conf_file

    console = _make_console()
    expanded = path.expanduser().resolve()
    try:
        return read_and_validate_conf_file(expanded)
    except FileNotFoundError:
        console.print(f"[red]Config file not found:[/red] {expanded}")
        raise typer.Exit(code=1)
    except OSError as e:
        console.print(f"[red]Failed to read config file {expanded}:[/red] {e}")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON in {expanded}:[/red] {e}")
        raise typer.Exit(code=1)
    except ValidationError as e:
        console.print(f"[red]Config validation failed for {expanded}:[/red]\n{e}")
        raise typer.Exit(code=1)


def _ensure_cli_config_available(cli_cwd: Path) -> None:
    """Verify CLI runtime configuration is available via env var or conf file.

    When a config file is found on disk, it is validated and its raw contents
    are loaded into ``GIGA_AGENT_CLI_CONFIG`` so the rest of the runtime reads
    from a single, pre-validated source.
    """
    if os.environ.get("GIGA_AGENT_CLI_CONFIG", "").strip():
        return

    from giga_agent.core.agent.cli_conf import CONF_FILENAME, conf_search_paths
    from giga_agent.core.paths import giga_agent_dir

    candidates = conf_search_paths(cli_cwd)
    for candidate in candidates:
        if candidate.is_file():
            os.environ["GIGA_AGENT_CLI_CONFIG"] = _load_and_validate_config_file(
                candidate
            )
            return

    from rich.syntax import Syntax

    example = (
        "{\n"
        '  "llm": {\n'
        '    "connector": { "__type": "openai", "api_key": "sk-..." },\n'
        '    "__type": "openai",\n'
        '    "model_id": "gpt-4o"\n'
        "  },\n"
        '  "sandbox": "local_jupyter"\n'
        "}"
    )

    project_dir = giga_agent_dir()
    process_cwd = Path.cwd().resolve()

    console = _make_console()
    console.print("[red]CLI runtime configuration not found.[/red]\n")
    console.print("Provide configuration in one of the following ways:")
    console.print(f"  • Create [bold]{CONF_FILENAME}[/bold] in {cli_cwd}")
    if process_cwd != cli_cwd:
        console.print(f"  • Or create it in {process_cwd}")
    console.print(f"  • Or create it in {project_dir}")
    console.print("  • Or pass JSON via the [bold]--config[/bold] option")
    console.print(
        "  • Or set the [bold]GIGA_AGENT_CLI_CONFIG[/bold] env var to a JSON string\n"
    )
    console.print(f"Example {CONF_FILENAME}:")
    console.print(
        Syntax(example, "json", theme="ansi_dark", background_color="default")
    )
    raise typer.Exit(code=1)


def _stop_supervised_processes_once(
    *,
    stop_state: dict[str, bool],
    reason: str,
) -> None:
    if stop_state.get("done"):
        return
    stop_state["done"] = True
    try:
        stopped = get_process_supervisor().stop_all()
    except Exception:
        return
    if stopped:
        console = _make_console()
        console.print(
            f"[dim]Stopped {len(stopped)} managed subprocess(es) during {reason}.[/dim]"
        )


async def _chat_loop(
    graph,
    checkpointer,
    state: _ChatState,
    render_markdown: bool,
    cwd: Path,
    prompt: str | None = None,
    plan_mode: bool = False,
    no_python_tool: bool = False,
    python_executor: str = "worker",
) -> None:
    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    console = _make_console()

    resolver = await RuntimeResolver.create(
        {
            "configurable": {
                "langgraph_auth_user": {
                    "identity": "00000000-0000-0000-0000-000000000000"
                }
            }
        }
    )
    user = resolver.user

    thread_id = str(uuid4())
    config = _make_cli_thread_config(
        thread_id=thread_id,
        checkpointer=checkpointer,
        user_id=str(user.id),
        no_python_tool=no_python_tool,
    )
    if prompt is not None:
        config = dict(config)
        metadata = dict(config.get("metadata") or {})
        metadata["cli_prompt_mode"] = True
        config["metadata"] = metadata

    console.print("[bold green]GigaAgent CLI[/bold green]")
    console.print(f"Thread: {thread_id}")
    if prompt is not None:
        prepared_turn = _prepare_cli_turn(
            prompt,
            cwd=cwd,
            base_config=config,
            plan_mode_pending=plan_mode,
            auto_approve=state.approve,
        )
        if prepared_turn.get("command") == "plan_pending":
            console.print(
                "[yellow]Режим планирования включён. Следующее сообщение будет отправлено в plan mode.[/yellow]"
            )
            return
        if prepared_turn.get("consumes_plan_mode_pending"):
            state.plan_mode_pending = False
        try:
            if _is_cli_context_compaction_turn(prepared_turn["config"]):
                with console.status(
                    "[cyan]Chat summarization in progress...[/cyan]",
                    spinner="dots",
                ):
                    await _stream_and_handle_interrupts(
                        graph,
                        prepared_turn["input_msg"],
                        prepared_turn["config"],
                        console,
                        state,
                        render_markdown,
                    )
            else:
                await _stream_and_handle_interrupts(
                    graph,
                    prepared_turn["input_msg"],
                    prepared_turn["config"],
                    console,
                    state,
                    render_markdown,
                )
            if _is_cli_context_compaction_turn(prepared_turn["config"]):
                await _print_context_compaction_status(
                    console, graph, prepared_turn["config"]
                )
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n[dim]Interrupted.[/dim]")
        return

    console.print("Type your message. Press Ctrl+C or Ctrl+D to exit.")
    console.print(
        "[dim]Hotkeys: Shift+Tab toggle auto-approve · Ctrl+O toggle tool debug logs.[/dim]\n"
    )

    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    message_prompt_session = _make_message_prompt_session(cwd, state)

    def _raise_keyboard_interrupt(signum, frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    try:
        while True:
            try:
                user_input = await message_prompt_session.prompt_async()
            except UnicodeDecodeError as e:
                _print_input_encoding_error(console, e)
                continue
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

            if not user_input.strip():
                continue

            prepared_turn = _prepare_cli_turn(
                user_input,
                cwd=cwd,
                base_config=config,
                plan_mode_pending=state.plan_mode_pending,
                auto_approve=state.approve,
            )
            if prepared_turn.get("command") == "new_chat":
                if python_executor == "worker":
                    try:
                        graph_state = await graph.aget_state(config)
                        kernel_id = graph_state.values.get("kernel_id")
                    except Exception:
                        kernel_id = None
                    if isinstance(kernel_id, str):
                        from giga_agent.sandbox.local_jupyter.worker_manager import (
                            get_local_python_worker_manager,
                        )

                        await get_local_python_worker_manager().stop_kernel(kernel_id)
                state.plan_mode_pending = False
                thread_id = str(uuid4())
                config = _make_cli_thread_config(
                    thread_id=thread_id,
                    checkpointer=checkpointer,
                    user_id=str(user.id),
                    no_python_tool=no_python_tool,
                )
                console.print(
                    f"[yellow]Начат новый чат.[/yellow] [dim]Thread: {thread_id}[/dim]"
                )
                continue
            if prepared_turn.get("command") == "plan_pending":
                console.print(
                    "[yellow]Режим планирования включён. Следующее сообщение будет отправлено в plan mode.[/yellow]"
                )
                state.plan_mode_pending = True
                continue
            if prepared_turn.get("consumes_plan_mode_pending"):
                state.plan_mode_pending = False
            try:
                if _is_cli_context_compaction_turn(prepared_turn["config"]):
                    with console.status(
                        "[cyan]Chat summarization in progress...[/cyan]",
                        spinner="dots",
                    ):
                        await _stream_and_handle_interrupts(
                            graph,
                            prepared_turn["input_msg"],
                            prepared_turn["config"],
                            console,
                            state,
                            render_markdown,
                        )
                else:
                    await _stream_and_handle_interrupts(
                        graph,
                        prepared_turn["input_msg"],
                        prepared_turn["config"],
                        console,
                        state,
                        render_markdown,
                    )
                if _is_cli_context_compaction_turn(prepared_turn["config"]):
                    await _print_context_compaction_status(
                        console, graph, prepared_turn["config"]
                    )
            except (KeyboardInterrupt, asyncio.CancelledError):
                console.print("\n[dim]Interrupted.[/dim]")
                break
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)


async def _stream_raw_tokens(
    graph, input_msg, config, console, state: _ChatState
) -> str:
    from langchain_core.messages import AIMessageChunk, ToolMessage

    collected_text = ""
    try:
        async for event in graph.astream(
            input_msg, config, stream_mode=["messages", "custom", "updates"]
        ):
            activity = _extract_subagent_activity_event(event)
            if activity is not None:
                _handle_subagent_activity(console, state.subagent_statuses, activity)
                continue
            update_tool_calls = _extract_cli_update_tool_calls(event)
            if update_tool_calls:
                _print_cli_tool_calls(
                    console, update_tool_calls, state, render_markdown=False
                )
                continue
            message_event = _extract_cli_message_event(event)
            if message_event is None:
                continue
            msg, metadata = message_event

            if _is_subagent_message_event(metadata):
                continue

            if isinstance(msg, ToolMessage):
                if _is_think_tool_message(msg):
                    await _print_think_thoughts_for_tool_message(
                        graph, config, msg, console, render_markdown=False
                    )
                    continue
                if state.debug:
                    _print_tool_response(console, msg)
                continue

            if isinstance(msg, AIMessageChunk):
                _print_streamed_tool_calls(console, msg, state, render_markdown=False)

            if isinstance(msg, AIMessageChunk) and msg.content:
                collected_text, delta = _merge_stream_content(
                    collected_text, msg.content
                )
                if not delta:
                    continue
                if collected_text == delta:
                    console.print("[bold green]Agent:[/bold green] ", end="")
                print(delta, end="", flush=True)
    finally:
        _stop_subagent_statuses(state.subagent_statuses)

    if collected_text:
        print()
    return collected_text


async def _stream_with_live_markdown(
    graph,
    input_msg,
    config,
    console,
    state: _ChatState,
) -> str:
    from langchain_core.messages import AIMessageChunk, ToolMessage
    from rich.live import Live

    collected_text = ""
    pending_text = ""
    started_output = False
    token_count = 0
    live = None

    def start_live():
        active_live = Live(
            _markdown(""),
            console=console,
            auto_refresh=False,
            transient=True,
            vertical_overflow="crop",
        )
        active_live.start()
        return active_live

    def commit_chunk(chunk: str) -> None:
        nonlocal live
        if live is not None:
            _safe_stop_live(live)
            live = None
        console.print(_markdown(_format_text_with_attachments(chunk)))
        if chunk.endswith(("\n\n", "\r\n\r\n")):
            console.print()

    try:
        async for event in graph.astream(
            input_msg, config, stream_mode=["messages", "custom", "updates"]
        ):
            activity = _extract_subagent_activity_event(event)
            if activity is not None:
                _handle_subagent_activity(console, state.subagent_statuses, activity)
                continue
            update_tool_calls = _extract_cli_update_tool_calls(event)
            if update_tool_calls:
                _print_cli_tool_calls(
                    console, update_tool_calls, state, render_markdown=True
                )
                continue
            message_event = _extract_cli_message_event(event)
            if message_event is None:
                continue
            msg, metadata = message_event

            if _is_subagent_message_event(metadata):
                continue

            if isinstance(msg, ToolMessage):
                if _is_think_tool_message(msg):
                    if live is not None:
                        _safe_stop_live(live)
                        live = None
                    if pending_text.strip():
                        console.print(
                            _markdown(_format_text_with_attachments(pending_text))
                        )
                        pending_text = ""
                    await _print_think_thoughts_for_tool_message(
                        graph, config, msg, console, render_markdown=True
                    )
                    continue
                if state.debug:
                    _print_tool_response(console, msg)
                continue

            if isinstance(msg, AIMessageChunk):
                _print_streamed_tool_calls(console, msg, state, render_markdown=True)

            if isinstance(msg, AIMessageChunk) and msg.content:
                collected_text, delta = _merge_stream_content(
                    collected_text, msg.content
                )
                if not delta:
                    continue
                if not started_output:
                    console.print("[bold green]Agent:[/bold green]")
                    live = start_live()
                    started_output = True
                pending_text += delta
                chunks, pending_text = _pop_committable_markdown_chunks(pending_text)
                for chunk in chunks:
                    commit_chunk(chunk)
                if live is None:
                    live = start_live()
                token_count += 1
                if live is not None and token_count % 3 == 0:
                    live.update(
                        _markdown(pending_text + "▌"),
                        refresh=True,
                    )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if live is not None:
            _safe_stop_live(live)
        _stop_subagent_statuses(state.subagent_statuses)

    if pending_text.strip():
        console.print(_markdown(_format_text_with_attachments(pending_text)))
    return collected_text


async def _stream_and_handle_interrupts(
    graph,
    input_msg,
    config,
    console,
    state: _ChatState,
    render_markdown: bool,
) -> None:
    from langgraph.types import Command

    approve_prompt_session = None

    while True:
        if render_markdown:
            try:
                await _stream_with_live_markdown(
                    graph, input_msg, config, console, state
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
        else:
            try:
                await _stream_raw_tokens(
                    graph,
                    input_msg,
                    config,
                    console,
                    state,
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass

        graph_state = await graph.aget_state(config)
        tool_calls = _extract_tool_calls(graph_state)
        _print_cli_tool_calls(console, tool_calls, state, render_markdown)
        if not graph_state.next:
            break

        interrupt_value = _extract_interrupt_value(graph_state)
        if (
            isinstance(interrupt_value, dict)
            and interrupt_value.get("type") == "questions"
        ):
            resume_value = await _prompt_for_questions_interrupt(
                interrupt_value,
                console,
                state,
            )
            input_msg = Command(resume=resume_value)
            continue
        if (
            isinstance(interrupt_value, dict)
            and interrupt_value.get("type") == "plan_approval"
        ):
            resume_value = await _prompt_for_plan_approval_interrupt(
                interrupt_value,
                console,
                state,
                render_markdown=render_markdown,
                auto_approve=await _is_cli_prompt_mode(config),
            )
            input_msg = Command(resume=resume_value)
            continue

        if not tool_calls:
            resume_value = {"type": "approve"}
            input_msg = Command(resume=resume_value)
            continue

        if state.approve:
            resume_value = {"type": "approve"}
        else:
            if approve_prompt_session is None:
                approve_prompt_session = _make_approve_prompt_session(state)

            try:
                answer = (await approve_prompt_session.prompt_async()).strip()
            except UnicodeDecodeError as e:
                _print_input_encoding_error(console, e)
                resume_value = {"type": "comment", "message": "Tool call rejected."}
                input_msg = Command(resume=resume_value)
                continue
            except EOFError:
                raise KeyboardInterrupt

            if state.approve:
                resume_value = {"type": "approve"}
            elif answer.lower() in ("", "y", "yes"):
                resume_value = {"type": "approve"}
            elif answer.lower() in ("n", "no"):
                resume_value = {"type": "comment", "message": ""}
            else:
                resume_value = {"type": "comment", "message": answer}

        input_msg = Command(resume=resume_value)


def _extract_tool_calls(state) -> list[dict]:
    values = state.values
    messages = values.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            return msg.tool_calls
    return []


def _tool_call_id(tool_call: dict) -> str:
    call_id = tool_call.get("id")
    if call_id:
        return str(call_id)
    return json.dumps(
        {
            "name": tool_call.get("name"),
            "args": tool_call.get("args", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _print_cli_tool_calls(
    console,
    tool_calls: list[dict],
    state: _ChatState,
    render_markdown: bool,
) -> None:
    for tool_call in tool_calls:
        call_id = _tool_call_id(tool_call)
        if call_id in state.displayed_tool_call_ids:
            continue
        state.displayed_tool_call_ids.add(call_id)
        if _is_think_tool_call(tool_call):
            _print_think_thoughts(console, tool_call, render_markdown)
        elif state.approve:
            console.print(f"  [dim][Tool: {_format_tool_call(tool_call)}][/dim]")
        else:
            console.print(f"  [yellow][Tool: {_format_tool_call(tool_call)}][/yellow]")


def _print_streamed_tool_calls(
    console, message, state: _ChatState, *, render_markdown: bool
) -> None:
    tool_calls: list[dict[str, Any]] = []
    emitted_chunk_keys: set[str] = set()
    for chunk in getattr(message, "tool_call_chunks", None) or []:
        if not isinstance(chunk, dict):
            continue
        key = str(chunk.get("id") or f"index:{chunk.get('index', 0)}")
        pending = state.pending_tool_call_chunks.setdefault(
            key,
            {"id": chunk.get("id"), "name": "", "args_text": ""},
        )
        if chunk.get("name"):
            pending["name"] = chunk["name"]
        args_part = chunk.get("args")
        if isinstance(args_part, str):
            pending["args_text"] += args_part
        elif isinstance(args_part, dict):
            pending["args"] = args_part
        if "args" not in pending:
            try:
                pending["args"] = json.loads(pending["args_text"] or "")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not pending.get("name"):
            continue
        tool_calls.append(
            {
                "id": pending.get("id"),
                "name": pending["name"],
                "args": pending.get("args") or {},
            }
        )
        emitted_chunk_keys.add(key)
        state.pending_tool_call_chunks.pop(key, None)

    for tool_call in getattr(message, "tool_calls", None) or []:
        if not isinstance(tool_call, dict) or not tool_call.get("name"):
            continue
        key = str(tool_call.get("id") or "")
        if key in emitted_chunk_keys:
            continue
        if key in state.pending_tool_call_chunks and not tool_call.get("args"):
            continue
        state.pending_tool_call_chunks.pop(key, None)
        tool_calls.append(tool_call)
    if tool_calls:
        _print_cli_tool_calls(console, tool_calls, state, render_markdown)


def _extract_interrupt_value(state) -> Any | None:
    interrupts = getattr(state, "interrupts", None) or []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        if value is not None:
            return value
        if isinstance(interrupt, dict) and interrupt.get("value") is not None:
            return interrupt["value"]
    return None


def _build_cli_question_choices(
    options: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    choices = [
        (str(option.get("id", "")), str(option.get("text", "")).strip())
        for option in options
        if str(option.get("id", "")).strip()
    ]
    choices.append((_CLI_CUSTOM_QUESTION_VALUE, "Свой вариант"))
    return choices


def _build_cli_question_answer(
    question_id: str,
    *,
    question_type: str,
    selection: str | list[str] | None,
    custom_text: str = "",
) -> dict[str, Any] | None:
    normalized_custom_text = custom_text.strip()

    if question_type == "multi":
        selected_values = [
            str(value).strip() for value in (selection or []) if str(value).strip()
        ]
    elif isinstance(selection, str):
        selected_values = [selection.strip()] if selection.strip() else []
    else:
        selected_values = []

    use_custom_text = _CLI_CUSTOM_QUESTION_VALUE in selected_values
    selected_ids = [
        value for value in selected_values if value != _CLI_CUSTOM_QUESTION_VALUE
    ]

    if use_custom_text and not normalized_custom_text:
        return None
    if not selected_ids and not normalized_custom_text:
        return None

    return {
        "question_id": question_id,
        "selected": selected_ids,
        "other_text": normalized_custom_text if use_custom_text else "",
    }


def _is_cli_question_answered(
    *,
    question_type: str,
    selected_values: set[str],
    custom_text: str,
) -> bool:
    return (
        _build_cli_question_answer(
            "__check__",
            question_type=question_type,
            selection=(
                list(selected_values)
                if question_type == "multi"
                else next(iter(selected_values), None)
            ),
            custom_text=custom_text,
        )
        is not None
    )


def _render_cli_question_prompt(
    *,
    question_number: int,
    total_questions: int,
    question: dict[str, Any],
    cursor_index: int,
    selected_values: set[str],
    custom_text: str,
    error_message: str = "",
) -> list[tuple[str, str]]:
    question_text = str(question.get("text", ""))
    question_type = str(question.get("type", "single"))
    choices = question.get("choices") or []
    is_multi = question_type == "multi"
    fragments: list[tuple[str, str]] = [
        (
            "class:questions-help",
            f"Question {question_number}/{total_questions}  Left/Right: prev/next\n",
        ),
        ("class:questions-title", f"{question_text}\n"),
        (
            "class:questions-help",
            "Up/Down: move  Enter: select  Esc: skip"
            + ("  Space: toggle" if is_multi else "")
            + "\n\n",
        ),
    ]
    if error_message:
        fragments.extend(
            [
                ("class:questions-error", error_message),
                ("", "\n\n"),
            ]
        )

    for index, (value, label) in enumerate(choices, start=1):
        is_current = index - 1 == cursor_index
        is_selected = value in selected_values
        number_style = (
            "class:questions-option.current-number"
            if is_current
            else "class:questions-option.number"
        )
        text_style = (
            "class:questions-option.current-text"
            if is_current
            else "class:questions-option.text"
        )
        marker = "[x]" if is_selected else "[ ]" if is_multi else " • "
        rendered_label = label
        if value == _CLI_CUSTOM_QUESTION_VALUE:
            rendered_label = f"{label}:"
            if custom_text.strip():
                rendered_label = f"{rendered_label} {custom_text.strip()}"
        fragments.extend(
            [
                ("class:questions-option.mark", f"{marker} "),
                (number_style, f"{index}. "),
                (text_style, rendered_label),
                ("", "\n"),
            ]
        )
    return fragments


def _normalize_cli_questions(questions: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id", "")).strip()
        if not question_id:
            continue
        raw_options = question.get("options")
        options = (
            [opt for opt in raw_options if isinstance(opt, dict)]
            if isinstance(raw_options, list)
            else []
        )
        normalized.append(
            {
                "id": question_id,
                "text": str(question.get("text", "")).strip() or f"Question {index}",
                "type": (
                    "multi"
                    if str(question.get("type", "single")).strip() == "multi"
                    else "single"
                ),
                "choices": _build_cli_question_choices(options),
            }
        )
    return normalized


def _next_cli_question_index(
    *,
    current_index: int,
    questions: list[dict[str, Any]],
    selected_by_question: list[set[str]],
    custom_text_by_question: list[str],
) -> int | None:
    total = len(questions)
    for offset in range(1, total + 1):
        candidate = (current_index + offset) % total
        if not _is_cli_question_answered(
            question_type=str(questions[candidate].get("type", "single")),
            selected_values=selected_by_question[candidate],
            custom_text=custom_text_by_question[candidate],
        ):
            return candidate
    return None


def _build_cli_questions_payload(
    questions: list[dict[str, Any]],
    selected_by_question: list[set[str]],
    custom_text_by_question: list[str],
) -> list[dict[str, Any]] | None:
    answers: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        answer = _build_cli_question_answer(
            str(question.get("id", "")),
            question_type=str(question.get("type", "single")),
            selection=(
                list(selected_by_question[index])
                if str(question.get("type", "single")) == "multi"
                else next(iter(selected_by_question[index]), None)
            ),
            custom_text=custom_text_by_question[index],
        )
        if answer is None:
            return None
        answers.append(answer)
    return answers


async def _prompt_for_cli_questions(
    *,
    state: _ChatState,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    if not questions:
        return []

    current_question_index = 0
    cursor_by_question = [0 for _ in questions]
    selected_by_question = [set() for _ in questions]
    custom_text_by_question = ["" for _ in questions]
    error_message = ""

    def current_question() -> dict[str, Any]:
        return questions[current_question_index]

    def current_choices() -> list[tuple[str, str]]:
        return list(current_question().get("choices") or [])

    def current_cursor_index() -> int:
        choices = current_choices()
        if not choices:
            return 0
        cursor_by_question[current_question_index] %= len(choices)
        return cursor_by_question[current_question_index]

    def current_value() -> str:
        return current_choices()[current_cursor_index()][0]

    def current_selected_values() -> set[str]:
        return selected_by_question[current_question_index]

    def current_custom_text() -> str:
        return custom_text_by_question[current_question_index]

    def current_question_type() -> str:
        return str(current_question().get("type", "single"))

    def is_custom_cursor() -> bool:
        return current_value() == _CLI_CUSTOM_QUESTION_VALUE

    def all_questions_answered() -> bool:
        return (
            _build_cli_questions_payload(
                questions,
                selected_by_question,
                custom_text_by_question,
            )
            is not None
        )

    def maybe_finish(app) -> bool:
        answers = _build_cli_questions_payload(
            questions,
            selected_by_question,
            custom_text_by_question,
        )
        if answers is None:
            return False
        app.exit(result=answers)
        return True

    def advance_or_finish(app) -> None:
        nonlocal current_question_index, error_message
        next_index = _next_cli_question_index(
            current_index=current_question_index,
            questions=questions,
            selected_by_question=selected_by_question,
            custom_text_by_question=custom_text_by_question,
        )
        if next_index is None:
            if not maybe_finish(app):
                app.invalidate()
            return
        current_question_index = next_index
        error_message = ""
        app.invalidate()

    def select_single_current() -> bool:
        nonlocal error_message
        current_selected_values().clear()
        current_selected_values().add(current_value())
        if is_custom_cursor():
            if not current_custom_text().strip():
                error_message = "Введите свой вариант."
                return False
        else:
            custom_text_by_question[current_question_index] = ""
        error_message = ""
        return True

    def toggle_multi_current() -> None:
        value = current_value()
        selected_values = current_selected_values()
        if value in selected_values:
            selected_values.remove(value)
        else:
            selected_values.add(value)

    def render_question():
        return _render_cli_question_prompt(
            question_number=current_question_index + 1,
            total_questions=len(questions),
            question=current_question(),
            cursor_index=current_cursor_index(),
            selected_values=current_selected_values(),
            custom_text=current_custom_text(),
            error_message=error_message,
        )

    kb = KeyBindings()

    @kb.add("up")
    def _move_up(event) -> None:
        choices = current_choices()
        if not choices:
            return
        cursor_by_question[current_question_index] = (
            current_cursor_index() - 1
        ) % len(choices)
        event.app.invalidate()

    @kb.add("down")
    def _move_down(event) -> None:
        choices = current_choices()
        if not choices:
            return
        cursor_by_question[current_question_index] = (
            current_cursor_index() + 1
        ) % len(choices)
        event.app.invalidate()

    @kb.add("left")
    def _move_left(event) -> None:
        nonlocal current_question_index, error_message
        current_question_index = (current_question_index - 1) % len(questions)
        error_message = ""
        event.app.invalidate()

    @kb.add("right")
    def _move_right(event) -> None:
        nonlocal current_question_index, error_message
        if current_question_index == len(questions) - 1 and all_questions_answered():
            maybe_finish(event.app)
            return
        current_question_index = (current_question_index + 1) % len(questions)
        error_message = ""
        event.app.invalidate()

    @kb.add("space", filter=Condition(lambda: current_question_type() == "multi"))
    def _toggle_current(event) -> None:
        toggle_multi_current()
        event.app.invalidate()

    @kb.add("enter", eager=True)
    def _submit(event) -> None:
        nonlocal error_message
        question_type = current_question_type()
        if question_type == "single":
            if not select_single_current():
                event.app.invalidate()
                return
            advance_or_finish(event.app)
            return
        toggle_multi_current()
        if (
            _CLI_CUSTOM_QUESTION_VALUE in current_selected_values()
            and not current_custom_text().strip()
        ):
            error_message = "Введите свой вариант."
        else:
            error_message = ""
        event.app.invalidate()

    @kb.add("backspace", filter=Condition(is_custom_cursor))
    @kb.add("c-h", filter=Condition(is_custom_cursor))
    def _erase_custom_char(event) -> None:
        nonlocal error_message
        current_text = current_custom_text()
        if current_text:
            custom_text_by_question[current_question_index] = current_text[:-1]
        error_message = ""
        event.app.invalidate()

    @kb.add("<any>", filter=Condition(is_custom_cursor))
    def _append_custom_char(event) -> None:
        nonlocal error_message
        data = event.data
        if not data or not data.isprintable():
            return
        custom_text_by_question[current_question_index] = current_custom_text() + data
        if current_question_type() == "single":
            current_selected_values().clear()
        current_selected_values().add(_CLI_CUSTOM_QUESTION_VALUE)
        error_message = ""
        event.app.invalidate()

    @kb.add("escape", eager=True)
    def _skip(event) -> None:
        event.app.exit(result=None)

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(render_question),
                always_hide_cursor=True,
            )
        ),
        key_bindings=merge_key_bindings([kb, _make_toggle_keybindings(state)]),
        style=_make_questions_choice_style(),
        mouse_support=False,
        full_screen=False,
    )
    return await app.run_async()


async def _prompt_for_question_text_answer(
    console,
    state: _ChatState,
    *,
    question_text: str,
    allow_empty: bool,
    prompt_text: str = "Custom answer: ",
    empty_error_text: str = "Custom answer cannot be empty.",
) -> str:
    prompt_session = _make_questions_prompt_session(
        state,
        prompt_text=prompt_text,
    )
    console.print(f"[dim]{question_text}[/dim]")
    while True:
        try:
            raw_answer = (await prompt_session.prompt_async()).strip()
        except UnicodeDecodeError as error:
            _print_input_encoding_error(console, error)
            continue
        except EOFError:
            raise KeyboardInterrupt
        if raw_answer or allow_empty:
            return raw_answer
        console.print(f"[red]{empty_error_text}[/red]")


async def _prompt_for_questions_interrupt(
    interrupt_value: dict[str, Any],
    console,
    state: _ChatState,
) -> dict[str, Any]:
    questions = interrupt_value.get("questions")
    if not isinstance(questions, list) or not questions:
        return {"type": "comment", "message": ""}

    normalized_questions = _normalize_cli_questions(questions)
    answers = await _prompt_for_cli_questions(
        state=state,
        questions=normalized_questions,
    )
    if answers is None:
        comment = await _prompt_for_question_text_answer(
            console,
            state,
            question_text="Optional skip comment. Leave empty to skip without comment.",
            allow_empty=True,
        )
        return {"type": "comment", "message": comment}
    return {"answers": answers}


def _normalize_cli_plan_todos(raw_todos: Any) -> list[dict[str, str]]:
    if not isinstance(raw_todos, list):
        return []

    normalized: list[dict[str, str]] = []
    for index, todo in enumerate(raw_todos, start=1):
        if not isinstance(todo, dict):
            continue
        content = str(todo.get("content", "")).strip()
        if not content:
            continue
        normalized_todo = {
            "id": str(todo.get("id", "")).strip() or str(index),
            "content": content,
        }
        note = str(todo.get("note", "")).strip()
        if note:
            normalized_todo["note"] = note
        status = str(todo.get("status", "")).strip()
        if status:
            normalized_todo["status"] = status
        normalized.append(normalized_todo)
    return normalized


def _extract_plan_approval_payload(interrupt_value: Any) -> dict[str, Any] | None:
    if not isinstance(interrupt_value, dict):
        return None
    if interrupt_value.get("type") != "plan_approval":
        return None
    return {
        "plan_content": str(interrupt_value.get("plan_content") or "").strip(),
        "todos": _normalize_cli_plan_todos(interrupt_value.get("todos")),
    }


def _print_plan_approval_card(
    console,
    *,
    plan_content: str,
    todos: list[dict[str, str]],
    render_markdown: bool,
) -> None:
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    renderables: list[Any] = [
        Text("План готов. Подтвердите его или отправьте на доработку.", style="bold")
    ]

    if plan_content:
        renderables.append(Text(""))
        if render_markdown:
            renderables.append(_markdown(_format_text_with_attachments(plan_content)))
        else:
            renderables.append(Text(plan_content))

    if todos:
        todo_lines = []
        for index, todo in enumerate(todos, start=1):
            line = f"{index}. {todo['content']}"
            note = todo.get("note")
            if note:
                line += f" ({note})"
            status = todo.get("status")
            if status and status != "pending":
                line += f" [{status}]"
            todo_lines.append(line)
        renderables.extend(
            [
                Text(""),
                Text(f"Шаги ({len(todos)}):", style="bold"),
                Text("\n".join(todo_lines)),
            ]
        )

    console.print(
        Panel(
            Group(*renderables),
            title="План на подтверждение",
            border_style="cyan",
            expand=True,
        )
    )


async def _prompt_for_plan_approval_interrupt(
    interrupt_value: dict[str, Any],
    console,
    state: _ChatState,
    *,
    render_markdown: bool,
    auto_approve: bool = False,
) -> dict[str, Any]:
    payload = _extract_plan_approval_payload(interrupt_value)
    if payload is None:
        return {"action": "approve"}

    _print_plan_approval_card(
        console,
        plan_content=payload["plan_content"],
        todos=payload["todos"],
        render_markdown=render_markdown,
    )

    if auto_approve:
        return {"action": "approve"}

    prompt_session = _make_approve_prompt_session(
        state,
        prompt_text="Подтвердить план? [Y/n]: ",
    )
    while True:
        try:
            answer = (await prompt_session.prompt_async()).strip()
        except UnicodeDecodeError as error:
            _print_input_encoding_error(console, error)
            continue
        except EOFError:
            raise KeyboardInterrupt

        lowered = answer.lower()
        if lowered in ("", "y", "yes"):
            return {"action": "approve"}
        if lowered in ("n", "no"):
            feedback = await _prompt_for_question_text_answer(
                console,
                state,
                question_text="Что нужно изменить в плане?",
                allow_empty=False,
                prompt_text="Замечания: ",
                empty_error_text="Замечания к доработке не могут быть пустыми.",
            )
            return {"action": "reject", "feedback": feedback}
        if answer:
            return {"action": "reject", "feedback": answer}


def _truncate(value, max_len: int = 40) -> str:
    s = str(value)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _single_line_preview(value: str, max_len: int = 90) -> str:
    preview = " ".join(value.strip().split())
    if len(preview) > max_len:
        preview = preview[: max_len - 3] + "..."
    return preview


def _format_tool_arg_value(value) -> str:
    if isinstance(value, str):
        return repr(_single_line_preview(value))
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes {len(value)}>"
    if isinstance(value, dict):
        return _single_line_preview(str(value), max_len=90)
    if isinstance(value, (list, tuple, set)):
        return _single_line_preview(str(value), max_len=90)
    return _truncate(value, max_len=90)


def _format_tool_args(args: dict | None) -> str:
    if not args:
        return ""
    items = list(args.items())
    rendered = [f"{key}={_format_tool_arg_value(value)}" for key, value in items[:3]]
    if len(items) > 3:
        rendered.append(f"+{len(items) - 3} more")
    return ", ".join(rendered)


def _format_tool_call(tool_call: dict) -> str:
    args_str = _format_tool_args(tool_call.get("args", {}))
    name = tool_call.get("name", "tool")
    return f"{name}({args_str})" if args_str else str(name)


def _is_think_tool_call(tool_call: dict) -> bool:
    return tool_call.get("name") == "think"


def _print_think_thoughts(console, tool_call: dict, render_markdown: bool) -> None:
    args = tool_call.get("args") or {}
    thoughts = args.get("thoughts") or args.get("thought") or ""
    thoughts = str(thoughts).strip()
    if not thoughts:
        return
    console.print("[dim bold]Thoughts:[/dim bold]")
    if render_markdown:
        console.print(
            _markdown(_format_text_with_attachments(thoughts)),
            style="dim",
        )
    else:
        console.print(thoughts, style="dim", markup=False)


def _format_tool_response_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list, tuple)):
        return json.dumps(content, ensure_ascii=False, indent=2, default=str)
    return str(content)


def _print_tool_response(console, message) -> None:
    from rich.text import Text

    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    name = (
        additional_kwargs.get("tool_name") or getattr(message, "name", None) or "tool"
    )
    content = _format_tool_response_content(getattr(message, "content", ""))
    content = content.strip() or "(empty)"

    console.print(Text(f"  [Tool response: {name}]", style="cyan"))
    console.print(
        Text("\n".join(f"    {line}" for line in content.splitlines()), style="dim")
    )


def _tool_message_name(message) -> str | None:
    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    return additional_kwargs.get("tool_name") or getattr(message, "name", None)


def _is_think_tool_message(message) -> bool:
    return _tool_message_name(message) == "think"


def _context_compaction_payload(message) -> dict[str, Any] | None:
    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    namespace = additional_kwargs.get("giga_agent")
    if not isinstance(namespace, dict):
        return None
    payload = namespace.get("context_compaction")
    return payload if isinstance(payload, dict) else None


def _latest_context_compaction_result(state) -> tuple[str, str] | None:
    values = getattr(state, "values", {}) or {}
    messages = values.get("messages", []) or []
    for message in reversed(messages):
        payload = _context_compaction_payload(message)
        if payload is None:
            continue
        status = payload.get("status")
        if not isinstance(status, str):
            continue
        content = _format_tool_response_content(getattr(message, "content", "")).strip()
        return status, content
    return None


async def _print_context_compaction_status(console, graph, config) -> None:
    state = await graph.aget_state(config)
    result = _latest_context_compaction_result(state)
    if result is None:
        console.print("[red]Context summarization failed.[/red]")
        return
    status, content = result
    if status == "completed":
        console.print("[green]Chat summarized successfully.[/green]")
        return
    if content:
        console.print(content, style="red", markup=False)
        return
    console.print("[red]Context summarization failed.[/red]")


async def _print_think_thoughts_for_tool_message(
    graph, config, message, console, render_markdown: bool
) -> None:
    tool_call_id = getattr(message, "tool_call_id", None)
    if not tool_call_id:
        return
    try:
        state = await graph.aget_state(config)
    except Exception:
        return
    for m in state.values.get("messages", []):
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("id") == tool_call_id and tc.get("name") == "think":
                _print_think_thoughts(console, tc, render_markdown)
                return


def cli_chat(
    graph_and_app_path: Annotated[
        str,
        typer.Argument(
            help="Path to graph and app, e.g. giga_agent.agents.run:graph:app"
        ),
    ] = "giga_agent.agents.run:graph:app",
    log_level: Annotated[
        LogLevel, typer.Option(help="Logging level", case_sensitive=False)
    ] = LogLevel.ERROR,
    approve: Annotated[
        bool, typer.Option("--approve", help="Auto-approve all tool calls")
    ] = False,
    plan: Annotated[
        bool,
        typer.Option(
            "--plan",
            help="Use plan mode for the first message before executing it.",
        ),
    ] = False,
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            help="Send one user message non-interactively and exit when the agent finishes.",
        ),
    ] = None,
    no_markdown: Annotated[
        bool,
        typer.Option(
            "--no-markdown", help="Disable Markdown rendering (show raw text)"
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Print debug details, including tool responses"),
    ] = False,
    cwd: Annotated[
        Path | None,
        typer.Option(
            "--cwd",
            help="Agent working directory for local CLI sandbox execution.",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="CLI runtime configuration as a JSON string (overrides giga_agent.conf.json).",
        ),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config-file",
            help=(
                "Path to a CLI runtime config JSON file. The contents are "
                "validated and then loaded into GIGA_AGENT_CLI_CONFIG."
            ),
        ),
    ] = None,
    no_sandbox: Annotated[
        bool,
        typer.Option(
            "--no-sandbox",
            help="Disable local_jupyter sandbox safe-execution and write-dir policy.",
        ),
    ] = False,
    no_python_tool: Annotated[
        bool,
        typer.Option(
            "--no-python-tool",
            help="Disable the Python tool in the REPL.",
        ),
    ] = False,
    python_executor: Annotated[
        str,
        typer.Option(
            "--python-executor",
            help="Python executor for local_jupyter: jupyter or worker.",
            case_sensitive=False,
        ),
    ] = "worker",
) -> None:
    """
    Interactive CLI chat: invoke the agent graph directly (no HTTP server).
    """
    setup_cli_logging(log_level.value.upper())
    os.environ.setdefault("GIGA_AGENT_LOG_LEVEL", log_level.value)

    # .env → os.environ до чтения настроек (per-service креды берутся os.getenv).
    load_dev_env()

    from giga_agent.core.paths import ensure_giga_agent_dir

    cli_cwd = (cwd or Path.cwd()).expanduser().resolve()
    cli_cwd.mkdir(parents=True, exist_ok=True)

    ensure_giga_agent_dir()
    ensure_dev_secret_key_env()

    os.environ["GIGA_AGENT_RUNTIME"] = "cli"
    os.environ.setdefault("GIGA_AGENT_RUNTIME_LOCAL", "true")
    os.environ["GIGA_AGENT_CLI_CWD"] = str(cli_cwd)
    normalized_python_executor = python_executor.strip().lower()
    if normalized_python_executor not in {"jupyter", "worker"}:
        _make_console().print(
            "[red]--python-executor must be either 'jupyter' or 'worker'.[/red]"
        )
        raise typer.Exit(code=1)
    os.environ["GIGA_AGENT_CLI_PYTHON_EXECUTOR"] = normalized_python_executor
    if no_sandbox:
        os.environ["GIGA_AGENT_CLI_NO_SANDBOX"] = "true"
    if config is not None and config_file is not None:
        _make_console().print(
            "[red]Pass either --config or --config-file, not both.[/red]"
        )
        raise typer.Exit(code=1)
    if config is not None:
        os.environ["GIGA_AGENT_CLI_CONFIG"] = config
    elif config_file is not None:
        os.environ["GIGA_AGENT_CLI_CONFIG"] = _load_and_validate_config_file(
            config_file
        )

    _ensure_cli_config_available(cli_cwd)
    reset_settings_cache()

    from giga_agent.core.cache import setup_cache

    setup_cache()

    console = _make_console()
    stop_state: dict[str, bool] = {}

    with console.status("[bold green]Loading agent..."):
        from ._langgraph_config import build_langgraph_runtime_config

        try:
            langgraph_runtime_config = build_langgraph_runtime_config(
                graph_and_app_path
            )
        except KeyboardInterrupt:
            raise typer.Exit(code=130)

        agent = langgraph_runtime_config["agent"]
        compiled_graph = agent.graph

    console.print(f"[green]Agent loaded[/green] with {len(agent.all_modules)} modules.")

    chat_state = _ChatState(
        approve=approve or prompt is not None,
        debug=debug,
        plan_mode_pending=plan,
    )

    async def _run() -> None:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from giga_agent.core.paths import giga_agent_dir

        db_dir = giga_agent_dir() / "langgraph"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "checkpoints.db"

        try:
            async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
                await _chat_loop(
                    compiled_graph,
                    checkpointer,
                    chat_state,
                    not no_markdown,
                    cli_cwd,
                    prompt,
                    plan_mode=plan,
                    no_python_tool=no_python_tool,
                    python_executor=normalized_python_executor,
                )
        finally:
            if normalized_python_executor == "worker":
                from giga_agent.sandbox.local_jupyter.worker_manager import (
                    get_local_python_worker_manager,
                )

                await get_local_python_worker_manager().stop_all()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    finally:
        _stop_supervised_processes_once(
            stop_state=stop_state,
            reason="CLI shutdown",
        )
