"""Telegram bot runner – starts/stops aiogram bots per user."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.enums import ParseMode
from langgraph_sdk import get_client

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.auth.security import create_access_token
from giga_agent.modules.telegram.models import (
    TelegramBot as TelegramBotModel,
    TelegramBotRepository,
)

logger = get_logger(__name__)

ASSISTANT_ID = "giga_agent"


def _langgraph_url() -> str:
    settings = get_settings()
    return settings.giga_agent_langgraph_api_url or "http://localhost:8000"


def _make_token(user_id: uuid.UUID, email: str) -> str:
    return create_access_token(
        data={"sub": email, "user_id": str(user_id)},
    )


class _BotInstance:
    """Wraps a single aiogram Bot + Dispatcher pair for one user."""

    def __init__(self, bot_row: TelegramBotModel, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email
        self.bot = Bot(token=bot_row.bot_token)
        self.dp = Dispatcher()
        self._task: asyncio.Task | None = None
        self._setup_handlers()

    def _setup_handlers(self):
        @self.dp.message()
        async def _on_message(message: tg_types.Message):
            if not message.text:
                return
            await self._handle_message(message)

    async def _handle_message(self, message: tg_types.Message):
        chat_id = message.chat.id
        text = message.text or ""
        user_id = self.bot_row.user_id

        try:
            token = _make_token(user_id, self.user_email)
            client = get_client(
                url=_langgraph_url(),
                headers={"Authorization": f"Bearer {token}"},
            )

            session_factory = await get_session_factory()
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                thread_row = await repo.get_thread(self.bot_row.id, chat_id)

                if thread_row is None:
                    thread = await client.threads.create(
                        metadata={"telegram_chat_id": str(chat_id)},
                    )
                    thread_id = thread["thread_id"]
                    await repo.create_thread(self.bot_row.id, chat_id, thread_id)
                else:
                    thread_id = thread_row.langgraph_thread_id

            await message.chat.do("typing")

            response_chunks: list[str] = []
            async for event in client.runs.stream(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                input={"messages": [{"role": "human", "content": text}]},
                stream_mode="messages",
                config={"configurable": {"auto_approve": True}},
            ):
                if hasattr(event, "event") and event.event == "messages/complete":
                    for msg_data in event.data if isinstance(event.data, list) else [event.data]:
                        if isinstance(msg_data, dict):
                            role = msg_data.get("type") or msg_data.get("role", "")
                            content = msg_data.get("content", "")
                            if role == "ai" and content and not msg_data.get("tool_calls"):
                                response_chunks.append(content)

            if response_chunks:
                full_response = "\n".join(response_chunks)
                for chunk in _split_message(full_response):
                    await message.answer(chunk)
            else:
                await message.answer("✅ Задача выполнена.")

        except Exception:
            logger.exception("Error handling Telegram message for user %s", user_id)
            try:
                await message.answer("⚠️ Произошла ошибка при обработке сообщения.")
            except Exception:
                pass

    async def start(self):
        logger.info(
            "Starting Telegram bot %s for user %s",
            self.bot_row.bot_username or self.bot_row.id,
            self.bot_row.user_id,
        )
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            await self.dp.start_polling(self.bot, handle_signals=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Telegram bot polling failed for %s", self.bot_row.id)

    async def stop(self):
        logger.info("Stopping Telegram bot %s", self.bot_row.id)
        if self._task and not self._task.done():
            await self.dp.stop_polling()
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.bot.session.close()


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


class TelegramBotManager:
    """Manages all running Telegram bot instances."""

    def __init__(self):
        self._bots: dict[uuid.UUID, _BotInstance] = {}

    async def start_all(self):
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            bots = await repo.get_all_enabled()
            for bot_row in bots:
                await self._start_bot(bot_row, session)

    async def _start_bot(self, bot_row: TelegramBotModel, session: Any):
        if bot_row.id in self._bots:
            return

        from giga_agent.models.users import UserRepository
        user = await UserRepository(session).get_by_id(bot_row.user_id, use_cache=False)
        if user is None:
            logger.warning("User %s not found for Telegram bot %s", bot_row.user_id, bot_row.id)
            return

        try:
            instance = _BotInstance(bot_row, user.email)
            bot_info = await instance.bot.get_me()
            if bot_row.bot_username != bot_info.username:
                bot_row.bot_username = bot_info.username
                await session.commit()
            self._bots[bot_row.id] = instance
            await instance.start()
        except Exception:
            logger.exception("Failed to start Telegram bot %s", bot_row.id)

    async def start_bot(self, bot_id: uuid.UUID):
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            bot_row = await repo.get_by_id(bot_id)
            if bot_row and bot_row.is_enabled:
                await self._start_bot(bot_row, session)

    async def stop_bot(self, bot_id: uuid.UUID):
        instance = self._bots.pop(bot_id, None)
        if instance:
            await instance.stop()

    async def restart_bot(self, bot_id: uuid.UUID):
        await self.stop_bot(bot_id)
        await self.start_bot(bot_id)

    async def stop_all(self):
        for bot_id in list(self._bots.keys()):
            await self.stop_bot(bot_id)

    def is_running(self, bot_id: uuid.UUID) -> bool:
        return bot_id in self._bots


_manager: TelegramBotManager | None = None


def get_bot_manager() -> TelegramBotManager:
    global _manager
    if _manager is None:
        _manager = TelegramBotManager()
    return _manager
