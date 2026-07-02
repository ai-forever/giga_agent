"""Telegram bot application runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Dispatcher, types as tg_types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from giga_agent.channels.telegram.bot import create_telegram_bot
from giga_agent.channels.telegram.handlers.callbacks import TelegramCallbackHandlers
from giga_agent.channels.telegram.handlers.messages import TelegramMessageHandlers
from giga_agent.channels.telegram.runtime import get_bot_token
from giga_agent.channels.telegram.services.access import TelegramAccessService
from giga_agent.channels.telegram.services.media import TelegramMediaService
from giga_agent.channels.telegram.services.message_tool_runtime import (
    TelegramMessageToolRuntime,
)
from giga_agent.channels.telegram.services.threads import TelegramThreadService
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot

logger = get_logger(__name__)

# Telegram delivers an album/gallery as several separate updates that share a
# ``media_group_id``. We buffer them briefly and process the whole group as one
# logical message so it produces a single thread and a single agent run.
MEDIA_GROUP_DEBOUNCE_SECONDS = 1.0


def _has_supported_attachment(message: tg_types.Message | None) -> bool:
    if message is None:
        return False
    return bool(
        message.photo
        or message.document
        or message.voice
        or message.audio
        or message.video
        or message.video_note
        or message.sticker
    )


def _has_processable_reply_content(message: tg_types.Message | None) -> bool:
    if message is None:
        return False
    text = message.text or message.caption or ""
    return bool(text or _has_supported_attachment(message))


class TelegramBotApp:
    def __init__(self, bot_row: ChannelBot, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email
        self.bot = create_telegram_bot(get_bot_token(bot_row))
        self.dp = Dispatcher()
        self._task: asyncio.Task | None = None
        # media_group_id -> {"messages": [...], "task": asyncio.Task}
        self._media_groups: dict[str, dict[str, Any]] = {}
        self._media_group_lock = asyncio.Lock()

        self.access_service = TelegramAccessService(bot_row=bot_row, bot=self.bot)
        self.thread_service = TelegramThreadService(
            bot_row=bot_row,
            user_email=user_email,
        )
        self.media_service = TelegramMediaService(bot=self.bot, bot_row=bot_row)
        self.message_tool_runtime = TelegramMessageToolRuntime(
            media_service=self.media_service,
        )
        self.message_handlers = TelegramMessageHandlers(
            bot_row=bot_row,
            access_service=self.access_service,
            thread_service=self.thread_service,
            media_service=self.media_service,
            message_tool_runtime=self.message_tool_runtime,
        )
        self.callback_handlers = TelegramCallbackHandlers(
            bot_row=bot_row,
            access_service=self.access_service,
            thread_service=self.thread_service,
            media_service=self.media_service,
            message_tool_runtime=self.message_tool_runtime,
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.dp.message(Command("new"))
        async def _on_new(message: tg_types.Message):
            await self.message_handlers.handle_new(message)

        @self.dp.message(Command("message"))
        async def _on_message_command(message: tg_types.Message):
            await self.handle_message_command(message)

        @self.dp.message(Command("start"))
        async def _on_start(message: tg_types.Message):
            await self.message_handlers.handle_start(message)

        @self.dp.callback_query()
        async def _on_callback_query(callback: tg_types.CallbackQuery):
            await self.callback_handlers.handle_callback_query(callback)

        @self.dp.message()
        async def _on_message(message: tg_types.Message):
            text = message.text or message.caption or ""
            has_file = bool(
                message.photo
                or message.document
                or message.voice
                or message.audio
                or message.video
                or message.video_note
                or message.sticker
            )
            if not text and not has_file:
                return
            if message.media_group_id is not None:
                # An album's caption/@mention lives on a single part, so the
                # access decision is deferred to flush time and evaluated over
                # the whole group; per-part filtering here would drop the rest
                # of the gallery in group chats.
                await self._buffer_media_group(message)
                return
            if not self.access_service.should_process_message(message):
                return
            await self.handle_message(message)

    async def _buffer_media_group(self, message: tg_types.Message) -> None:
        """Collect album messages sharing a media_group_id and debounce a flush.

        Each incoming part restarts the timer; once no new part arrives within
        ``MEDIA_GROUP_DEBOUNCE_SECONDS`` the whole group is handled at once.
        """
        group_id = str(message.media_group_id)
        async with self._media_group_lock:
            buffer = self._media_groups.get(group_id)
            if buffer is None:
                buffer = {"messages": [], "task": None}
                self._media_groups[group_id] = buffer
            buffer["messages"].append(message)
            if buffer["task"] is not None:
                buffer["task"].cancel()
            buffer["task"] = asyncio.create_task(self._flush_media_group(group_id))

    async def _flush_media_group(self, group_id: str) -> None:
        try:
            await asyncio.sleep(MEDIA_GROUP_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        async with self._media_group_lock:
            buffer = self._media_groups.pop(group_id, None)
        if not buffer:
            return
        messages: list[tg_types.Message] = buffer["messages"]
        if not messages:
            return
        # Decide over the whole group: process only if some part is addressed to
        # the bot (always true in private chats; a reply/@mention in groups).
        processable = [
            m for m in messages if self.access_service.should_process_message(m)
        ]
        if not processable:
            return
        # The caption/@mention of an album lives on a single part; pick a
        # processable part (preferring one with text) as primary so handle_message
        # passes its own access check and the agent gets the user's text.
        primary = next((m for m in processable if (m.caption or m.text)), processable[0])
        extras = [m for m in messages if m is not primary]
        try:
            await self.handle_message(primary, extra_file_messages=extras)
        except Exception:
            logger.exception(
                "Failed to handle media group %s for bot %s",
                group_id,
                self.bot_row.id,
            )

    async def handle_new(self, message: tg_types.Message) -> None:
        await self.message_handlers.handle_new(message)

    async def handle_message_command(self, message: tg_types.Message) -> None:
        command_text = self.access_service.strip_command_prefix(
            message.text or message.caption or "",
            "message",
        )
        has_reply_content = _has_processable_reply_content(message.reply_to_message)
        if not command_text and not _has_supported_attachment(message) and not has_reply_content:
            await message.answer("После /message нужен текст или вложение для обработки.")
            return

        await self.message_handlers.handle_message(
            message,
            force_process=True,
            text_override=command_text,
        )

    async def handle_message(
        self,
        message: tg_types.Message,
        *,
        force_process: bool = False,
        reply_to_message_id: int | None = None,
        contact_message: tg_types.Message | None = None,
        text_override: str | None = None,
        extra_file_messages: list[tg_types.Message] | None = None,
    ) -> None:
        await self.message_handlers.handle_message(
            message,
            force_process=force_process,
            reply_to_message_id=reply_to_message_id,
            contact_message=contact_message,
            text_override=text_override,
            extra_file_messages=extra_file_messages,
        )

    async def handle_callback_query(self, callback: tg_types.CallbackQuery) -> None:
        await self.callback_handlers.handle_callback_query(callback)

    async def set_commands(self) -> None:
        private_commands = [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="new", description="Сбросить контекст диалога"),
            BotCommand(command="message", description="Отправить сообщение агенту"),
        ]
        group_commands = [
            BotCommand(command="new", description="Сбросить контекст диалога"),
            BotCommand(command="message", description="Отправить сообщение агенту"),
        ]

        await self.bot.set_my_commands(
            private_commands,
            scope=BotCommandScopeAllPrivateChats(),
        )
        await self.bot.set_my_commands(
            group_commands,
            scope=BotCommandScopeAllGroupChats(),
        )

    async def start(self) -> None:
        logger.info(
            "Starting Telegram bot %s for user %s",
            self.bot_row.bot_username or self.bot_row.id,
            self.bot_row.user_id,
        )
        await self.bot.delete_webhook(drop_pending_updates=True)
        await self.set_commands()
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            await self.dp.start_polling(self.bot, handle_signals=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Telegram bot polling failed for %s", self.bot_row.id)

    async def stop(self) -> None:
        logger.info("Stopping Telegram bot %s", self.bot_row.id)
        if self._task and not self._task.done():
            await self.dp.stop_polling()
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.bot.session.close()
