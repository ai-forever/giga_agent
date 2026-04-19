"""Telegram bot application runtime."""

from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

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


def _get_env_proxy(*names: str) -> str | None:
    for name in names:
        value = (os.getenv(name) or os.getenv(name.lower()) or "").strip()
        if value:
            return value
    return None


def _build_bot(token: str) -> Bot:
    proxy = _get_env_proxy("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY")
    if proxy:
        logger.info("Telegram bot session proxy enabled")
        return Bot(token=token, session=AiohttpSession(proxy=proxy))
    return Bot(token=token)


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
        self.bot = _build_bot(get_bot_token(bot_row))
        self.dp = Dispatcher()
        self._task: asyncio.Task | None = None

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
            if not self.access_service.should_process_message(message):
                return
            await self.handle_message(message)

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
    ) -> None:
        await self.message_handlers.handle_message(
            message,
            force_process=force_process,
            reply_to_message_id=reply_to_message_id,
            contact_message=contact_message,
            text_override=text_override,
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
