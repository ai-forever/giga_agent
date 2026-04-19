"""Telegram channel runtime."""

from __future__ import annotations

from pydantic import Field, PrivateAttr

from giga_agent.channels.telegram.app import TelegramBotApp
from giga_agent.channels.telegram.bot import create_telegram_bot
from giga_agent.channels.base import Channel, ChannelInstanceMetadata
from giga_agent.channels.registry import ChannelRegistry
from giga_agent.channels.telegram.constants import TELEGRAM_CHANNEL_TYPE
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.users import UserRepository

logger = get_logger(__name__)


@ChannelRegistry.register("telegram")
class TelegramChannel(Channel):
    channel_type = TELEGRAM_CHANNEL_TYPE

    bot_token: str = Field(min_length=1)
    _app: TelegramBotApp | None = PrivateAttr(default=None)

    @classmethod
    def get_prompt(cls) -> str:
        return """
КАНАЛ ДОСТАВКИ: TELEGRAM

Твой ответ будет отправлен пользователю в Telegram-чат.

# Инструмент `message`

У тебя есть инструмент `message` для отправки сообщений и файлов в Telegram.

Правила использования:
1. Если задача требует нескольких шагов, запуска субагентов или долгих вычислений — отправь короткое промежуточное уведомление через `message` с `expect_response=false`, чтобы пользователь знал, что ты работаешь. Не молчи надолго.
2. Когда нужно уточнить выбор у пользователя (опрос, варианты) — используй кнопки, а не текст. Разбивай на отдельные сообщения по одному вопросу.
3. Для отправки файлов (графиков, документов, изображений) используй поле `attachments` в `message`, указывая sandbox-путь к файлу.

# Форматирование ответов

- Пиши кратко и структурно. Telegram-сообщения читаются с телефона — избегай длинных стен текста.
- Используй **Markdown**: жирный, курсив, код, списки. Формат будет автоматически преобразован в Telegram MarkdownV2.
- НЕ используй HTML-теги и iframe.
- Содержимое тегов `<thinking>` автоматически удаляется перед отправкой — но ты обязан использовать их для рассуждений перед своим основным сообщением / вызовом инструментов. Помни , что пользователь не увидит <thinking> тег и ты не должен помещать в них полезный для пользователя текст.

# Артефакты и файлы

- Если в ходе решения задачи были сгенерированы графики, таблицы, изображения или другие файлы — ОБЯЗАТЕЛЬНО приложи их к финальному ответу через `attachments` инструмента `message` или в формате `[описание](attachment:путь)`.
- Plotly-графики в формате `.plotly.json` автоматически конвертируются в PNG при отправке.
- Не описывай содержимое графика словами, если можешь отправить сам файл.

# Контекст диалога

- Если пользователь ответил на твоё предыдущее сообщение (reply) — это продолжение задачи. Учитывай весь контекст.
- В групповых чатах обращайся к автору сообщения, а не ко всем участникам.
"""

    async def resolve_instance_metadata(self) -> ChannelInstanceMetadata:
        bot = create_telegram_bot(self.bot_token)
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
