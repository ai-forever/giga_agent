"""Schema and helpers for the Telegram message MCP tool."""

from __future__ import annotations

import html
from typing import Literal

from pydantic import BaseModel, Field

TELEGRAM_MESSAGE_TOOL_NAME = "message"
TELEGRAM_MESSAGE_TOOL_CHANNEL = "telegram"
TELEGRAM_MESSAGE_TOOL_KIND = "message"


class TelegramMessageAttachment(BaseModel):
    path: str = ""
    kind: Literal["image", "document", "audio", "video", "voice"] = "document"
    caption: str = ""
    filename: str = ""


class TelegramMessageButton(BaseModel):
    text: str = ""
    kind: Literal["callback", "url"] = "callback"
    value: str = ""
    url: str = ""


class TelegramMessageToolPayload(BaseModel):
    channel: Literal["telegram"] = TELEGRAM_MESSAGE_TOOL_CHANNEL
    kind: Literal["message"] = TELEGRAM_MESSAGE_TOOL_KIND
    content: str = Field(description="Markdown message shown to the Telegram user")
    buttons: list[TelegramMessageButton] = Field(default_factory=list)
    attachments: list[TelegramMessageAttachment] = Field(default_factory=list)
    expect_response: bool = True
    response_format: Literal["text", "single_choice", "multi_choice"] = "text"
    disable_web_page_preview: bool = False


def _normalize_message_tool_value(value: object) -> object:
    if isinstance(value, str):
        return html.unescape(value.replace("\\r\\n", "\n").replace("\\n", "\n"))
    if isinstance(value, list):
        return [_normalize_message_tool_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_message_tool_value(item) for key, item in value.items()}
    return value


def build_telegram_message_tool_schema() -> dict[str, object]:
    return {
        "name": TELEGRAM_MESSAGE_TOOL_NAME,
        "description": (
            "Отправляет сообщение пользователю в Telegram. Это твой единственный способ говорить с пользователем — "
            "и промежуточные уведомления, и финальный ответ отправляй через него. "
            "expect_response управляет тем, завершается ли твой ход (см. описание поля). "
            "Если ожидается выбор, например опрос, используй кнопки вместо текста. "
            "При проведении опроса, разбивай сообщение на несколько сообщений с ответом на несколько вопросов. "
            "Используй короткие и понятные текста в кнопках, если возможно."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Markdown message shown to the Telegram user.",
                },
                "buttons": {
                    "type": "array",
                    "description": "Telegram inline buttons",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Visible button text",
                            },
                            "kind": {
                                "type": "string",
                                "enum": ["callback", "url"],
                                "default": "callback",
                                "description": (
                                    "callback resumes the tool with the selected button; "
                                    "url opens a link."
                                ),
                            },
                            "value": {
                                "type": "string",
                                "default": "",
                                "description": (
                                    "Optional semantic value returned for callback buttons. "
                                    "If empty, the button text is returned."
                                ),
                            },
                            "url": {
                                "type": "string",
                                "default": "",
                                "description": "Destination URL for url buttons.",
                            },
                        },
                        "required": ["text"],
                    },
                },
                "attachments": {
                    "type": "array",
                    "description": "Optional files to send before the prompt.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Sandbox or bucket path.",
                            },
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "image",
                                    "document",
                                    "audio",
                                    "video",
                                    "voice",
                                ],
                                "default": "document",
                            },
                            "caption": {
                                "type": "string",
                                "default": "",
                            },
                            "filename": {
                                "type": "string",
                                "default": "",
                            },
                        },
                        "required": ["path"],
                    },
                },
                "expect_response": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "true — твой ход на этом завершается, управление у пользователя. Ставь для вопросов И для финального ответа: "
                        "ран остановится и дождётся следующего сообщения пользователя. "
                        "false — ты сразу продолжишь работу после отправки. Ставь ТОЛЬКО для промежуточных уведомлений "
                        "('я работаю над...'), чтобы не молчать во время долгой задачи. "
                        "Не завершай задачу сообщением с false — финал всегда отправляй с true."
                    ),
                },
                "response_format": {
                    "type": "string",
                    "enum": ["text", "single_choice"],
                    "default": "text",
                    "description": "Expected shape of the user's reply.",
                },
                "disable_web_page_preview": {
                    "type": "boolean",
                    "default": False,
                    "description": "Disable Telegram link previews for content.",
                },
            },
            "required": ["content"],
        },
    }


def parse_telegram_message_tool_payload(
    raw_args: dict[str, object] | None,
) -> TelegramMessageToolPayload:
    normalized_args = _normalize_message_tool_value(dict(raw_args or {}))
    normalized_args["content"] = normalized_args.get("content", "")
    return TelegramMessageToolPayload.model_validate(normalized_args)
