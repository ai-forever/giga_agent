"""Helpers for building Telegram message context payloads."""

from __future__ import annotations

from typing import Any

from aiogram import types as tg_types

from giga_agent.channels.telegram.utils import _describe_uploaded_files


def _format_message_author(message: tg_types.Message | None) -> tuple[str, str]:
    if message is None:
        return "unknown", "Unknown"

    author = getattr(message, "from_user", None) or getattr(message, "sender_chat", None)
    username = getattr(author, "username", None)
    username_value = f"@{username}" if username else "unknown"
    name_parts = [
        getattr(author, "first_name", None),
        getattr(author, "last_name", None),
    ]
    full_name = " ".join(part for part in name_parts if part).strip()
    if not full_name:
        full_name = getattr(author, "title", None) or "Unknown"
    return username_value, full_name


def build_reply_kwargs(reply_to_message_id: int | None) -> dict[str, Any]:
    if reply_to_message_id is None:
        return {}
    return {
        "reply_parameters": tg_types.ReplyParameters(message_id=reply_to_message_id)
    }


def build_message_context_payload(
    *,
    label: str,
    message: tg_types.Message | None,
    text: str,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    username, full_name = _format_message_author(message)
    attachments: list[str] = []
    seen: set[str] = set()
    for file_data in files:
        if not isinstance(file_data, dict):
            continue
        path = file_data.get("path")
        if path and path not in seen:
            attachments.append(path)
            seen.add(path)
    return {
        "label": label,
        "username": username,
        "full_name": full_name,
        "text": text or "[empty]",
        "files": files,
        "attachments": attachments,
    }


def build_message_context(
    *,
    label: str,
    message: tg_types.Message,
    text: str,
    files: list[dict[str, Any]],
) -> str:
    payload = build_message_context_payload(
        label=label,
        message=message,
        text=text,
        files=files,
    )
    lines = [
        f"{payload['label']}:",
        f"Ник: {payload['username']}",
        f"Имя: {payload['full_name']}",
        "Текст сообщения:",
        payload["text"],
    ]
    if payload["files"]:
        lines.extend(
            [
                "Файлы:",
                _describe_uploaded_files(payload["files"]),
            ]
        )
    return "\n".join(lines)
