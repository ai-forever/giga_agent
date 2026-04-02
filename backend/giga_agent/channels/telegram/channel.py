"""Telegram channel runtime."""

from __future__ import annotations

from aiogram import Bot
from pydantic import Field, PrivateAttr

from giga_agent.channels.telegram.app import TelegramBotApp
from giga_agent.channels.base import Channel, ChannelInstanceMetadata
from giga_agent.channels.registry import ChannelRegistry
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.users import UserRepository

logger = get_logger(__name__)


@ChannelRegistry.register("telegram")
class TelegramChannel(Channel):
    channel_type = "telegram"

    bot_token: str = Field(min_length=1)
    _app: TelegramBotApp | None = PrivateAttr(default=None)

    async def resolve_instance_metadata(self) -> ChannelInstanceMetadata:
        bot = Bot(token=self.bot_token)
        try:
            me = await bot.get_me()
        finally:
            await bot.session.close()
        return ChannelInstanceMetadata(bot_username=me.username)

    async def start(self, bot: ChannelBot) -> None:
        if self._app is not None:
            return

        session_factory = await get_session_factory()
        async with session_factory() as session:
            user = await UserRepository(session).get_by_id(bot.user_id, use_cache=False)
            if user is None:
                logger.warning("User %s not found for bot %s", bot.user_id, bot.id)
                return

            app = TelegramBotApp(bot, user.email)
            bot_info = await app.bot.get_me()
            if bot.bot_username != bot_info.username:
                repo = ChannelBotRepository(session)
                await repo.update(bot, bot_username=bot_info.username)
            self._app = app
            await self._app.start()

    async def stop(self, bot: ChannelBot) -> None:
        _ = bot
        if self._app is None:
            return

        app = self._app
        self._app = None
        await app.stop()

    async def restart(self, bot: ChannelBot) -> None:
        await self.stop(bot)
        await self.start(bot)
