"""Callback handlers for Telegram runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import types as tg_types

from giga_agent.channels.telegram.message_tool import (
    parse_telegram_message_tool_payload,
)
from giga_agent.channels.telegram.services.access import TelegramAccessService
from giga_agent.channels.telegram.services.media import TelegramMediaService
from giga_agent.channels.telegram.services.message_tool_runtime import (
    TelegramMessageToolRuntime,
    _resolve_callback_button,
)
from giga_agent.channels.telegram.services.threads import TelegramThreadService
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot, ChannelBotRepository

logger = get_logger(__name__)


class TelegramCallbackHandlers:
    def __init__(
        self,
        *,
        bot_row: ChannelBot,
        access_service: TelegramAccessService,
        thread_service: TelegramThreadService,
        media_service: TelegramMediaService,
        message_tool_runtime: TelegramMessageToolRuntime,
    ):
        self.bot_row = bot_row
        self.access_service = access_service
        self.thread_service = thread_service
        self.media_service = media_service
        self.message_tool_runtime = message_tool_runtime

    async def handle_callback_query(self, callback: tg_types.CallbackQuery) -> None:
        message = callback.message
        if message is None:
            await callback.answer()
            return
        if not await self.access_service.ensure_supported_chat(
            message, callback=callback
        ):
            return

        chat_id = message.chat.id
        user_id = self.bot_row.user_id
        request_start = datetime.now(timezone.utc)

        client = None
        try:
            session_factory = await get_session_factory()
            await self.access_service.register_contact(message)
            async with session_factory() as session:
                repo = ChannelBotRepository(session)
                contact = await repo.get_contact(self.bot_row.id, str(chat_id))
                if contact is None or not contact.is_approved:
                    await callback.answer("Контакт не подтверждён", show_alert=True)
                    return

            token = self.thread_service.create_token()
            client = self.thread_service.create_client(token)
            external_user_id = self.thread_service.resolve_external_user_id(message)

            async with session_factory() as session:
                repo = ChannelBotRepository(session)
                thread_id = await self.thread_service.get_or_create_thread(
                    client,
                    repo,
                    chat_id,
                    external_user_id,
                )

            pending_tool_calls = (
                await self.message_tool_runtime.get_pending_message_tool_calls(
                    client,
                    thread_id,
                )
            )
            if not pending_tool_calls:
                await callback.answer("Ожидание ответа уже завершено")
                return

            pending_tool_call = pending_tool_calls[-1]
            prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
            resolved = _resolve_callback_button(prompt, callback.data)
            if resolved is None:
                await callback.answer("Кнопка больше неактуальна", show_alert=True)
                return

            selected_button, response_text = resolved
            await callback.answer()
            result = await self.message_tool_runtime.resume_message_tool_calls(
                message=message,
                client=client,
                thread_id=thread_id,
                pending_tool_calls=pending_tool_calls,
                response_tool_call=pending_tool_call,
                response_prompt=prompt,
                response_text=response_text,
                file_data=[],
                run_timeout=90,
                selected_button=selected_button,
            )
            result = await self.message_tool_runtime.continue_run_until_ready(
                message=message,
                client=client,
                thread_id=thread_id,
                token=token,
                result=result,
                run_timeout=90,
            )
            if isinstance(result, dict) and result.get("messages"):
                await self.media_service.send_run_result(
                    message=message,
                    token=token,
                    result=result,
                    request_start=request_start,
                )
        except asyncio.TimeoutError:
            await callback.answer("Истекло время ожидания", show_alert=True)
        except Exception:
            logger.exception("Error handling Telegram callback for user %s", user_id)
            try:
                await callback.answer("Не удалось обработать нажатие", show_alert=True)
            except Exception:
                pass
        finally:
            if client is not None:
                await client.aclose()
