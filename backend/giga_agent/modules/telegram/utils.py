"""Shared helpers for the Telegram integration."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from aiogram import types as tg_types
from plotly import io as plotly_io

from giga_agent.conf import GIGA_AGENT_PREFIX_API, get_settings
from giga_agent.modules.auth.security import create_access_token
from giga_agent.modules.telegram.message_tool import (
    TELEGRAM_MESSAGE_TOOL_CHANNEL,
    TELEGRAM_MESSAGE_TOOL_NAME,
    TelegramMessageToolPayload,
)

_ATTACHMENT_RE = re.compile(r"!\[([^\]]*)\]\(attachment:(/?[^)]+)\)")

_BUCKET_PATH_RE = re.compile(
    r"(?:`?)(/bucket/[a-f0-9\-]+/[^\s`\"',)]+\.(?:png|jpg|jpeg|gif|webp|mp3|mp4|pdf|svg))(?:`?)",
    re.IGNORECASE,
)


def _langgraph_url() -> str:
    settings = get_settings()
    return settings.giga_agent_langgraph_api_url or "http://localhost:9090/api/"


def _agent_api_base() -> str:
    """Base URL for the agent's own FastAPI routes (mounted at /api)."""
    base = _langgraph_url().rstrip("/")
    return f"{base}{GIGA_AGENT_PREFIX_API}"


def _make_token(user_id: uuid.UUID, email: str) -> str:
    return create_access_token(
        data={"sub": email, "user_id": str(user_id)},
    )


def _strip_thinking(text: str) -> str:
    return re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()


def _extract_attachments(text: str) -> tuple[str, list[str]]:
    paths: list[str] = []
    for match in _ATTACHMENT_RE.finditer(text):
        paths.append(match.group(2))
    # Fallback: GigaChat often mentions /bucket/... paths as plain text
    if not paths:
        for match in _BUCKET_PATH_RE.finditer(text):
            p = match.group(1)
            if p not in paths:
                paths.append(p)
    cleaned = _ATTACHMENT_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, paths


def _find_last_human_index(messages: list) -> int:
    """Return the index of the last human message, or 0 if none found."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict):
            msg_type = messages[i].get("type") or messages[i].get("role", "")
            if msg_type == "human":
                return i
    return 0


def _scan_current_turn_attachments(result: dict) -> list[str]:
    """Scan only the current turn's messages for attachment paths."""
    paths: list[str] = []
    seen: set[str] = set()
    messages = result.get("messages") or []
    start = _find_last_human_index(messages)
    for msg in messages[start:]:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            for match in _ATTACHMENT_RE.finditer(content):
                p = match.group(2)
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        ak = msg.get("additional_kwargs") or {}
        for att in ak.get("attachments") or []:
            if isinstance(att, dict) and att.get("sandbox_path"):
                p = att["sandbox_path"]
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        for att in ak.get("tool_attachments") or []:
            if isinstance(att, dict) and att.get("sandbox_path"):
                p = att["sandbox_path"]
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        # Scan content for /bucket/ paths (both raw and inside JSON tool output)
        if isinstance(content, str):
            text_to_scan = content
            if content.startswith("{"):
                try:
                    tool_data = json.loads(content)
                    output = tool_data.get("output", "")
                    if isinstance(output, str):
                        text_to_scan = output
                except Exception:
                    pass
            for match in _ATTACHMENT_RE.finditer(text_to_scan):
                p = match.group(2)
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
            for match in _BUCKET_PATH_RE.finditer(text_to_scan):
                p = match.group(1)
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
    return paths


def _extract_ai_response(result: dict) -> tuple[str, list[str]]:
    messages = result.get("messages") or []
    text_parts: list[str] = []
    image_urls: list[str] = []

    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("type") or msg.get("role", "")
        if role != "ai":
            continue
        if msg.get("tool_calls"):
            continue

        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            cleaned = _strip_thinking(content)
            if cleaned:
                text_parts.append(cleaned)
            break
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        text_parts.append(block["text"].strip())
                    elif block.get("type") == "image_url":
                        url = block.get("image_url", {})
                        if isinstance(url, str):
                            image_urls.append(url)
                        elif isinstance(url, dict) and url.get("url"):
                            image_urls.append(url["url"])
                elif isinstance(block, str) and block.strip():
                    text_parts.append(block.strip())
            if text_parts:
                break

    return "\n\n".join(text_parts), image_urls


def _looks_like_plotly_figure(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    data = payload.get("data")
    if not isinstance(data, list):
        return False

    layout = payload.get("layout")
    if layout is not None and not isinstance(layout, dict):
        return False

    frames = payload.get("frames")
    if frames is not None and not isinstance(frames, list):
        return False

    allowed_keys = {"data", "layout", "frames", "config"}
    return bool(set(payload).intersection({"data", "layout", "frames"})) and set(
        payload
    ).issubset(allowed_keys)


def _plotly_json_to_png_bytes(*, payload_bytes: bytes) -> bytes | None:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not _looks_like_plotly_figure(payload):
        return None

    try:
        figure = plotly_io.from_json(json.dumps(payload, ensure_ascii=False))
        return figure.to_image(format="png")
    except ValueError:
        return None


def _state_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_telegram_message_tool_call(action: Any) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("name") != TELEGRAM_MESSAGE_TOOL_NAME:
        return False
    return isinstance(action.get("args") or {}, dict)


def _find_pending_message_tool_calls(thread_state: Any) -> list[dict[str, Any]]:
    pending_tool_calls: list[dict[str, Any]] = []
    interrupts = _state_get(thread_state, "interrupts", []) or []
    for interrupt_item in interrupts:
        value = _state_get(interrupt_item, "value", {}) or {}
        if not isinstance(value, dict) or value.get("type") != "tool_call":
            continue
        for tool_call in value.get("tools") or []:
            if _is_telegram_message_tool_call(tool_call):
                pending_tool_calls.append(tool_call)
    return pending_tool_calls


def _find_pending_message_tool_call(thread_state: Any) -> dict[str, Any] | None:
    pending_tool_calls = _find_pending_message_tool_calls(thread_state)
    return pending_tool_calls[-1] if pending_tool_calls else None


def _describe_uploaded_files(file_data: list[dict[str, Any]]) -> str:
    if not file_data:
        return ""
    names = [fd.get("original_name", "") or fd["path"] for fd in file_data]
    return "Прикреплён файл: " + ", ".join(names)


def _build_message_tool_result_parts(
    *,
    prompt: TelegramMessageToolPayload,
    response_text: str,
    file_data: list[dict[str, Any]],
    message: tg_types.Message | None,
    auto_response: bool = False,
    selected_button: str = "",
) -> list[dict[str, str]]:
    button_texts = {
        button.text
        for button in prompt.buttons
        if button.kind == "callback" and button.text
    }
    if not selected_button and response_text in button_texts:
        selected_button = response_text

    if auto_response:
        payload = {
            "content": "",
            "expect_response": False,
            "message": "Ты отправил уведомление пользователю (expect_response=False). Если тебе нужен ответ от пользователя, отправляй с expect_response=True.",
        }
    else:
        payload = {
            "channel": TELEGRAM_MESSAGE_TOOL_CHANNEL,
            "kind": "message_response",
            "content": response_text,
            "selected_button": selected_button,
            "response_format": prompt.response_format,
            "files": file_data,
            "auto_response": auto_response,
            "telegram_chat_id": message.chat.id if message else 0,
            "telegram_message_id": message.message_id if message else 0,
            "telegram_user": {
                "id": message.from_user.id if message and message.from_user else 0,
                "username": (
                    message.from_user.username if message and message.from_user else ""
                ),
                "first_name": (
                    message.from_user.first_name
                    if message and message.from_user
                    else ""
                ),
                "last_name": (
                    message.from_user.last_name if message and message.from_user else ""
                ),
            },
        }
    return [
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False),
        }
    ]


def _md_to_tg_markdown_v2(text: str) -> str:
    """Convert standard Markdown to Telegram MarkdownV2 format."""
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save_code_block, text)

    inline_codes: list[str] = []

    def _save_inline_code(match: re.Match) -> str:
        inline_codes.append(match.group(0))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", _save_inline_code, text)

    def _escape(value: str) -> str:
        return re.sub(r"([_\[\]()~>#+\-=|{}.!\\])", r"\\\1", value)

    parts = re.split(r"(\*\*(?:(?!\*\*).)+\*\*)", text)
    result_parts: list[str] = []
    for part in parts:
        match = re.match(r"^\*\*(.+)\*\*$", part, re.DOTALL)
        if match:
            result_parts.append(f"*{_escape(match.group(1))}*")
        else:
            sub_parts = re.split(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", part)
            for i, sub_part in enumerate(sub_parts):
                if i % 2 == 1:
                    result_parts.append(f"_{_escape(sub_part)}_")
                else:
                    result_parts.append(_escape(sub_part))

    text = "".join(result_parts)

    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)

    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    return text


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return parts
