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
1. `expect_response` управляет твоим ходом:
   - `expect_response=true` — твой ход завершён, управление у пользователя. Ставь для вопросов И для финального ответа. Ран остановится и дождётся следующего сообщения пользователя.
   - `expect_response=false` — ты сразу продолжишь работу. Ставь ТОЛЬКО для промежуточных уведомлений («я работаю над...»), чтобы не молчать во время долгой задачи.
2. Долгая задача (несколько шагов, субагенты, вычисления) → отправь короткое уведомление с `expect_response=false`, продолжай работу, а результат пришли отдельным сообщением с `expect_response=true`. Не молчи надолго.
3. Финал задачи ВСЕГДА отправляй через `message` с `expect_response=true`. Никогда не завершай ход просто текстом без вызова `message` и не заканчивай задачу сообщением с `expect_response=false`.
4. Когда нужно уточнить выбор у пользователя (опрос, варианты) — используй кнопки, а не текст. Разбивай на отдельные сообщения по одному вопросу.
5. Для отправки файлов (графиков, документов, изображений) используй поле `attachments` в `message`, указывая sandbox-путь к файлу.

# Как говорить с пользователем

- Всё содержимое `message` попадает пользователю в чат. Это живой диалог, а не отчёт о работе.
- Пиши от первого лица, обращаясь к пользователю («я посчитал...», «вот результат»), а НЕ от третьего лица про самого себя («агент сделал...», «бот отправил...»).
- После промежуточного уведомления (`expect_response=false`) пользователь уже видел, что ты сделал. Не пересказывай и не подытоживай свои действия — просто продолжай задачу.
- Когда всё готово: если есть что сказать — дай пользователю итог по существу; если добавить нечего — заверши коротким сообщением, без ретроспективы «что было сделано».

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

    async def deliver(
        self,
        bot: ChannelBot,
        external_chat_id: str,
        parts: list,
        *,
        token: str,
        external_user_id: str | None = None,
    ) -> bool:
        """Proactively send rendered parts to a Telegram chat.

        Only the bot token is needed for outbound, so this works even when the
        inbound polling app is not running.
        """
        from giga_agent.channels.telegram.services.media import TelegramMediaService

        tg_bot = create_telegram_bot(self.bot_token)
        try:
            media = TelegramMediaService(bot=tg_bot, bot_row=bot)
            return await media.send_parts_to_chat(
                chat_id=external_chat_id,
                token=token,
                parts=parts,
            )
        finally:
            await tg_bot.session.close()
