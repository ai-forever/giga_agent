"""Telegram bot application runtime."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from giga_agent.core.logging import get_logger
from giga_agent.modules.telegram.handlers.callbacks import TelegramCallbackHandlers
from giga_agent.modules.telegram.handlers.messages import TelegramMessageHandlers
from giga_agent.modules.telegram.models import TelegramBot as TelegramBotModel
from giga_agent.modules.telegram.services.access import TelegramAccessService
from giga_agent.modules.telegram.services.media import TelegramMediaService
from giga_agent.modules.telegram.services.message_tool_runtime import TelegramMessageToolRuntime
from giga_agent.modules.telegram.services.threads import TelegramThreadService

logger = get_logger(__name__)


class TelegramBotApp:
    def __init__(self, bot_row: TelegramBotModel, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email
        self.bot = Bot(token=bot_row.bot_token)
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
            await self.message_handlers.handle_message_command(message)

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
        await self.message_handlers.handle_message_command(message)

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
