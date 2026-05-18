"""Runtime support for Telegram message-tool interrupts."""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import types as tg_types
from aiogram.types import BufferedInputFile

from giga_agent.channels.telegram.constants import (
    ASSISTANT_ID,
    MESSAGE_TOOL_CALLBACK_PREFIX,
)
from giga_agent.channels.telegram.message_context import (
    build_message_context_payload,
    build_reply_kwargs,
)
from giga_agent.channels.telegram.message_tool import (
    TelegramMessageToolPayload,
    parse_telegram_message_tool_payload,
)
from giga_agent.channels.telegram.services.media import (
    TelegramMediaService,
    _convert_plotly_attachment,
)
from giga_agent.channels.telegram.runtime import build_memory_tags
from giga_agent.channels.telegram.utils import (
    _build_message_tool_result_parts,
    _describe_uploaded_files,
    _extract_text_media,
    _find_pending_message_tool_calls,
)
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def _build_inline_callback_data(button_index: int) -> str:
    return f"{MESSAGE_TOOL_CALLBACK_PREFIX}{button_index}"


def _parse_inline_callback_data(data: str | None) -> int | None:
    if not isinstance(data, str) or not data.startswith(MESSAGE_TOOL_CALLBACK_PREFIX):
        return None
    raw_index = data[len(MESSAGE_TOOL_CALLBACK_PREFIX) :]
    if not raw_index.isdigit():
        return None
    return int(raw_index)


def _build_prompt_reply_markup(
    prompt: TelegramMessageToolPayload,
) -> tg_types.InlineKeyboardMarkup | None:
    keyboard: list[list[tg_types.InlineKeyboardButton]] = []
    current_row: list[tg_types.InlineKeyboardButton] = []
    current_row_text_len = 0
    for index, button in enumerate(prompt.buttons):
        if not button.text:
            continue
        if button.kind == "url" and button.url:
            inline_button = tg_types.InlineKeyboardButton(
                text=button.text,
                url=button.url,
            )
        else:
            inline_button = tg_types.InlineKeyboardButton(
                text=button.text,
                callback_data=_build_inline_callback_data(index),
            )
        button_text_len = len(button.text)
        should_wrap = bool(
            current_row
            and (len(current_row) >= 4 or current_row_text_len + button_text_len > 20)
        )
        if should_wrap:
            keyboard.append(current_row)
            current_row = []
            current_row_text_len = 0

        current_row.append(inline_button)
        current_row_text_len += button_text_len

    if current_row:
        keyboard.append(current_row)

    if not keyboard:
        return None
    return tg_types.InlineKeyboardMarkup(inline_keyboard=keyboard)


def _resolve_callback_button(
    prompt: TelegramMessageToolPayload,
    callback_data: str | None,
) -> tuple[str, str] | None:
    button_index = _parse_inline_callback_data(callback_data)
    if button_index is None:
        return None
    buttons = [button for button in prompt.buttons if button.text]
    if button_index < 0 or button_index >= len(buttons):
        return None
    button = buttons[button_index]
    if button.kind == "url":
        return None
    response_text = button.value or button.text
    return button.text, response_text


class TelegramMessageToolRuntime:
    def __init__(self, *, media_service: TelegramMediaService):
        self.media_service = media_service

    async def has_active_run(
        self,
        client: Any,
        thread_id: str,
    ) -> bool:
        try:
            running_runs = await client.runs.list(
                thread_id,
                limit=1,
                status="running",
            )
            if running_runs:
                return True
            pending_runs = await client.runs.list(
                thread_id,
                limit=1,
                status="pending",
            )
        except Exception:
            logger.debug("Failed to fetch runs for %s", thread_id, exc_info=True)
            return False
        return bool(pending_runs)

    async def get_pending_message_tool_call(
        self,
        client: Any,
        thread_id: str,
    ) -> dict[str, Any] | None:
        pending_tool_calls = await self.get_pending_message_tool_calls(client, thread_id)
        return pending_tool_calls[-1] if pending_tool_calls else None

    async def get_pending_message_tool_calls(
        self,
        client: Any,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        try:
            thread_state = await client.threads.get_state(thread_id)
        except Exception:
            logger.debug("Failed to fetch thread state for %s", thread_id, exc_info=True)
            return []
        return _find_pending_message_tool_calls(thread_state)

    async def send_message_tool_prompt(
        self,
        message: tg_types.Message,
        token: str,
        tool_call: dict[str, Any],
        reply_to_message_id: int | None = None,
        include_reply_markup: bool = True,
    ) -> None:
        prompt = parse_telegram_message_tool_payload(tool_call.get("args"))
        reply_kwargs = build_reply_kwargs(reply_to_message_id)
        sent_attachment_paths: set[str] = set()
        for attachment in prompt.attachments:
            file_bytes = await self.media_service.download_attachment(token, attachment.path)
            if not file_bytes:
                continue
            filename = attachment.filename or attachment.path.rsplit("/", 1)[-1]
            file_bytes, filename, rendered_from_plotly = _convert_plotly_attachment(
                file_bytes=file_bytes,
                filename=filename,
            )
            input_file = BufferedInputFile(file_bytes, filename=filename)
            caption = attachment.caption or None
            kind = attachment.kind
            if rendered_from_plotly or kind == "image":
                await message.answer_photo(input_file, caption=caption, **reply_kwargs)
            elif kind == "audio":
                await message.answer_audio(input_file, caption=caption, **reply_kwargs)
            elif kind == "voice":
                await message.answer_voice(input_file, caption=caption, **reply_kwargs)
            elif kind == "video":
                await message.answer_video(input_file, caption=caption, **reply_kwargs)
            else:
                await message.answer_document(
                    input_file,
                    caption=caption,
                    **reply_kwargs,
                )
            if attachment.path:
                sent_attachment_paths.add(attachment.path)

        reply_markup = _build_prompt_reply_markup(prompt) if include_reply_markup else None
        parts = [
            part
            for part in _extract_text_media(prompt.content)
            if not (
                part["kind"] == "attachment_path"
                and part["value"] in sent_attachment_paths
            )
        ]
        await self.media_service.send_embedded_media(
            message=message,
            token=token,
            parts=parts,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            disable_web_page_preview=prompt.disable_web_page_preview,
        )

    async def continue_run_until_ready(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        token: str,
        result: Any,
        run_timeout: int,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        for _ in range(10):
            if not isinstance(result, dict):
                return None

            pending_message_tools = await self.get_pending_message_tool_calls(
                client,
                thread_id,
            )
            if pending_message_tools:
                last_pending_message_tool = pending_message_tools[-1]
                prompt = parse_telegram_message_tool_payload(
                    last_pending_message_tool.get("args"),
                )
                for index, pending_message_tool in enumerate(pending_message_tools):
                    await self.send_message_tool_prompt(
                        message,
                        token,
                        pending_message_tool,
                        reply_to_message_id,
                        include_reply_markup=index == len(pending_message_tools) - 1,
                    )
                if not prompt.expect_response:
                    result = await self.resume_message_tool_calls(
                        message=message,
                        client=client,
                        thread_id=thread_id,
                        pending_tool_calls=pending_message_tools,
                        response_tool_call=last_pending_message_tool,
                        response_prompt=prompt,
                        response_text="",
                        file_data=[],
                        run_timeout=run_timeout,
                        auto_response=True,
                    )
                    continue
                return None

            msgs = result.get("messages", [])
            last_ai = None
            for msg in reversed(msgs):
                if isinstance(msg, dict) and msg.get("type") == "ai":
                    last_ai = msg
                    break
            if last_ai and last_ai.get("tool_calls"):
                logger.info("Auto-approving tool calls for chat %s", message.chat.id)
                await message.chat.do("typing")
                result = await asyncio.wait_for(
                    client.runs.wait(
                        thread_id=thread_id,
                        assistant_id=ASSISTANT_ID,
                        input=None,
                        command={"resume": {"type": "approve"}},
                        config={
                            "configurable": {
                                "memory_disabled": False,
                                "memory_tags": build_memory_tags(message),
                                "memory_show_global": False,
                            },
                        },
                    ),
                    timeout=run_timeout,
                )
                continue
            return result
        return result if isinstance(result, dict) else None

    async def resume_message_tool_call(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        pending_tool_call: dict[str, Any],
        prompt: TelegramMessageToolPayload,
        response_text: str,
        file_data: list[dict[str, Any]],
        message_context: dict[str, Any] | None = None,
        attachment_paths: list[str] | None = None,
        reply_context: dict[str, Any] | None = None,
        run_timeout: int,
        auto_response: bool = False,
        selected_button: str = "",
    ) -> dict[str, Any]:
        return await self.resume_message_tool_calls(
            message=message,
            client=client,
            thread_id=thread_id,
            pending_tool_calls=[pending_tool_call],
            response_tool_call=pending_tool_call,
            response_prompt=prompt,
            response_text=response_text,
            file_data=file_data,
            message_context=message_context,
            attachment_paths=attachment_paths,
            reply_context=reply_context,
            run_timeout=run_timeout,
            auto_response=auto_response,
            selected_button=selected_button,
        )

    async def resume_message_tool_calls(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        pending_tool_calls: list[dict[str, Any]],
        response_tool_call: dict[str, Any],
        response_prompt: TelegramMessageToolPayload,
        response_text: str,
        file_data: list[dict[str, Any]],
        message_context: dict[str, Any] | None = None,
        attachment_paths: list[str] | None = None,
        reply_context: dict[str, Any] | None = None,
        run_timeout: int,
        auto_response: bool = False,
        selected_button: str = "",
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        response_tool_id = response_tool_call.get("id")
        for pending_tool_call in pending_tool_calls:
            is_response_tool = pending_tool_call.get("id") == response_tool_id
            if not is_response_tool:
                results.append({"id": pending_tool_call.get("id"), "result": {}})
                continue

            results.append(
                {
                    "id": pending_tool_call.get("id"),
                    "result": {
                        "content": _build_message_tool_result_parts(
                            prompt=response_prompt,
                            response_text=response_text,
                            file_data=file_data,
                            message_context=message_context,
                            attachment_paths=attachment_paths,
                            reply_context=reply_context,
                            message=message,
                            auto_response=auto_response,
                            selected_button=selected_button,
                        ),
                    },
                }
            )

        await message.chat.do("typing")
        return await asyncio.wait_for(
            client.runs.wait(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                input=None,
                command={
                    "resume": {
                        "type": "tool_call",
                        "results": results,
                    },
                },
                config={
                    "configurable": {
                        "memory_disabled": False,
                        "memory_tags": build_memory_tags(message),
                        "memory_show_global": False,
                    },
                },
            ),
            timeout=run_timeout,
        )

    async def resume_pending_message_tool(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        token: str,
        pending_tool_calls: list[dict[str, Any]],
        run_timeout: int,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        pending_tool_call = pending_tool_calls[-1]
        reply_message = getattr(message, "reply_to_message", None)
        reply_text = reply_message.text or reply_message.caption or "" if reply_message else ""
        reply_file_data: list[dict[str, Any]] = []
        if reply_message is not None:
            reply_file_data = await self.media_service.collect_incoming_files(
                reply_message,
                token,
                thread_id,
            )
        file_data = await self.media_service.collect_incoming_files(
            message,
            token,
            thread_id,
        )
        text = message.text or message.caption or ""
        response_text = text or _describe_uploaded_files(file_data)
        message_context = build_message_context_payload(
            label="Входящее сообщение",
            message=message,
            text=text,
            files=file_data,
        )
        prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
        result = await self.resume_message_tool_calls(
            message=message,
            client=client,
            thread_id=thread_id,
            pending_tool_calls=pending_tool_calls,
            response_tool_call=pending_tool_call,
            response_prompt=prompt,
            response_text=response_text,
            file_data=file_data,
            message_context=message_context,
            attachment_paths=message_context["attachments"],
            reply_context=build_message_context_payload(
                label="Прикрепено сообщение",
                message=reply_message,
                text=reply_text,
                files=reply_file_data,
            )
            if reply_message is not None
            else None,
            run_timeout=run_timeout,
        )
        return await self.continue_run_until_ready(
            message=message,
            client=client,
            thread_id=thread_id,
            token=token,
            result=result,
            run_timeout=run_timeout,
            reply_to_message_id=reply_to_message_id,
        )
