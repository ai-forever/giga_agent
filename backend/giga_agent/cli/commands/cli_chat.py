from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.logging import setup_cli_logging
from giga_agent.core.process_supervisor import get_process_supervisor

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
    __slots__ = ("approve", "debug")

    def __init__(self, approve: bool, debug: bool) -> None:
        self.approve = approve
        self.debug = debug


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


def _make_message_prompt_session(cwd: Path, state: _ChatState):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.filters import completion_is_selected, has_completions
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
    from prompt_toolkit.styles import Style

    from ._at_file_completer import make_at_file_completer

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
            "completion-menu.completion.current at-file.symbol": "fg:ansibrightmagenta nobold",
            "completion-menu.completion.current at-file.path": "fg:ansibrightcyan bold",
            "scrollbar.background": "bg:default",
            "scrollbar.button": "bg:ansibrightblack",
            **_BOTTOM_TOOLBAR_STYLE,
        }
    )

    return PromptSession(
        message=[("class:message-prompt", "You: ")],
        mouse_support=False,
        style=style,
        completer=make_at_file_completer(cwd),
        complete_while_typing=True,
        key_bindings=merge_key_bindings([kb, _make_toggle_keybindings(state)]),
        bottom_toolbar=_make_bottom_toolbar(state),
        reserve_space_for_menu=0,
    )


def _make_approve_prompt_session(state: _ChatState):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style

    return PromptSession(
        message=[("class:approve-prompt", "Approve? [Y/n]: ")],
        mouse_support=False,
        style=Style.from_dict({"approve-prompt": "bold", **_BOTTOM_TOOLBAR_STYLE}),
        key_bindings=_make_toggle_keybindings(state),
        bottom_toolbar=_make_bottom_toolbar(state),
        reserve_space_for_menu=0,
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
) -> None:
    from langchain_core.messages import HumanMessage
    from langgraph.constants import CONFIG_KEY_CHECKPOINTER

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
    config = {
        "configurable": {
            "thread_id": thread_id,
            CONFIG_KEY_CHECKPOINTER: checkpointer,
            "langgraph_auth_user": {"identity": str(user.id), "token": ""},
        }
    }

    console.print("[bold green]GigaAgent CLI[/bold green]")
    console.print(f"Thread: {thread_id}")
    if prompt is not None:
        input_msg = {
            "messages": [HumanMessage(content=_expand_at_file_refs(prompt, cwd))]
        }
        try:
            await _stream_and_handle_interrupts(
                graph, input_msg, config, console, state, render_markdown
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

            input_msg = {
                "messages": [
                    HumanMessage(content=_expand_at_file_refs(user_input, cwd))
                ]
            }
            try:
                await _stream_and_handle_interrupts(
                    graph, input_msg, config, console, state, render_markdown
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
    async for event in graph.astream(input_msg, config, stream_mode="messages"):
        if isinstance(event, tuple) and len(event) == 2:
            msg, metadata = event
        else:
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

        if isinstance(msg, AIMessageChunk) and msg.content:
            collected_text, delta = _merge_stream_content(collected_text, msg.content)
            if not delta:
                continue
            if collected_text == delta:
                console.print("[bold green]Agent:[/bold green] ", end="")
            print(delta, end="", flush=True)

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
        async for event in graph.astream(input_msg, config, stream_mode="messages"):
            if isinstance(event, tuple) and len(event) == 2:
                msg, metadata = event
            else:
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
        if not graph_state.next:
            break

        tool_calls = _extract_tool_calls(graph_state)
        if not tool_calls:
            resume_value = {"type": "approve"}
            input_msg = Command(resume=resume_value)
            continue

        if state.approve:
            for tc in tool_calls:
                if _is_think_tool_call(tc):
                    _print_think_thoughts(console, tc, render_markdown)
                else:
                    console.print(f"  [dim][Tool: {_format_tool_call(tc)}][/dim]")
            resume_value = {"type": "approve"}
        else:
            for tc in tool_calls:
                if _is_think_tool_call(tc):
                    _print_think_thoughts(console, tc, render_markdown)
                else:
                    console.print(f"  [yellow][Tool: {_format_tool_call(tc)}][/yellow]")

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
    )

    async def _run() -> None:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from giga_agent.core.paths import giga_agent_dir

        db_dir = giga_agent_dir() / "langgraph"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "checkpoints.db"

        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
            await _chat_loop(
                compiled_graph,
                checkpointer,
                chat_state,
                not no_markdown,
                cli_cwd,
                prompt,
            )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    finally:
        _stop_supervised_processes_once(
            stop_state=stop_state,
            reason="CLI shutdown",
        )
