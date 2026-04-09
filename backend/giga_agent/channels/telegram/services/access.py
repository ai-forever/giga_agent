"""Access control and contact registration for Telegram runtime."""

from __future__ import annotations

import re
from typing import Any

from aiogram import Bot, types as tg_types

from giga_agent.channels.telegram.constants import (
    GROUP_CHAT_TYPES,
    SUPPORTED_CHAT_TYPES,
)
from giga_agent.channels.telegram.runtime import (
    get_bot_username,
    get_contact_external_user_id,
)
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot, ChannelBotRepository

logger = get_logger(__name__)


class TelegramAccessService:
    def __init__(self, *, bot_row: ChannelBot, bot: Bot):
        self.bot_row = bot_row
        self.bot = bot

    def strip_bot_mentions(self, text: str) -> str:
        username = get_bot_username(self.bot_row)
        if not text or not username:
            return text

        without_mentions = re.sub(
            rf"(?i)(?<!\w)@{re.escape(username)}\b",
            "",
            text,
        )
        without_mentions = re.sub(r"[ \t]{2,}", " ", without_mentions)
        without_mentions = re.sub(r"\n{3,}", "\n\n", without_mentions)
        return without_mentions.strip()

    def strip_command_prefix(self, text: str, command: str) -> str:
        if not text:
            return text

        bot_username = re.escape(get_bot_username(self.bot_row) or "")
        command_pattern = rf"^/{re.escape(command)}(?:@{bot_username})?(?:\s+|$)"
        stripped = re.sub(command_pattern, "", text, count=1, flags=re.IGNORECASE)
        stripped = re.sub(r"^[ \t]+", "", stripped)
        return stripped

    async def ensure_supported_chat(
        self,
        message: tg_types.Message,
        *,
        callback: tg_types.CallbackQuery | None = None,
    ) -> bool:
        chat_type = getattr(message.chat, "type", None)
        if chat_type in SUPPORTED_CHAT_TYPES:
            return True

        if callback is not None:
            await callback.answer("Этот тип чата не поддерживается", show_alert=True)
        else:
            await message.answer(
                "Этот тип чата пока не поддерживается. Используйте личный чат, группу или супергруппу."
            )
        return False

    def should_process_message(self, message: tg_types.Message) -> bool:
        chat_type = getattr(message.chat, "type", None)
        if chat_type == "private":
            return True
        if chat_type not in GROUP_CHAT_TYPES:
            return False

        reply_message = getattr(message, "reply_to_message", None)
        if self.is_current_bot_message(reply_message):
            return True

        text = message.text or message.caption or ""
        entities = list(getattr(message, "entities", None) or []) + list(
            getattr(message, "caption_entities", None) or []
        )
        username = (get_bot_username(self.bot_row) or "").lower()
        if not username:
            return False

        for entity in entities:
            entity_type = getattr(entity, "type", None)
            if entity_type == "mention":
                offset = getattr(entity, "offset", 0)
                length = getattr(entity, "length", 0)
                mention = text[offset : offset + length].lower()
                if mention == f"@{username}":
                    return True
            if entity_type == "text_mention":
                entity_user = getattr(entity, "user", None)
                if entity_user is None:
                    continue
                entity_user_username = getattr(entity_user, "username", None)
                if entity_user_username and entity_user_username.lower() == username:
                    return True
                bot_id = getattr(self.bot, "id", None)
                if bot_id is not None and getattr(entity_user, "id", None) == bot_id:
                    return True

        return False

    def is_current_bot_message(self, message: tg_types.Message | None) -> bool:
        reply_user = getattr(message, "from_user", None)
        if reply_user is None or not getattr(reply_user, "is_bot", False):
            return False

        reply_username = getattr(reply_user, "username", None)
        bot_username = get_bot_username(self.bot_row)
        if bot_username and reply_username:
            if reply_username.lower() == bot_username.lower():
                return True

        bot_id = getattr(self.bot, "id", None)
        if bot_id is not None and getattr(reply_user, "id", None) == bot_id:
            return True

        return False

    async def register_contact(self, message: tg_types.Message) -> None:
        """Upsert the current Telegram chat as a contact."""
        try:
            contact_payload = self._build_contact_payload(message)
            session_factory = await get_session_factory()
            async with session_factory() as session:
                repo = ChannelBotRepository(session)
                await repo.upsert_contact(
                    bot_id=self.bot_row.id,
                    external_chat_id=str(message.chat.id),
                    external_user_id=get_contact_external_user_id(message),
                    **contact_payload,
                )
        except Exception:
            logger.warning("Failed to register contact for chat %s", message.chat.id)

    def _build_contact_payload(self, message: tg_types.Message) -> dict[str, Any]:
        chat = message.chat
        chat_type = getattr(chat, "type", None)
        chat_title = getattr(chat, "title", None)
        chat_username = getattr(chat, "username", None)

        if chat_type == "private":
            tg_user = message.from_user
            return {
                "chat_type": chat_type,
                "chat_title": None,
                "username": (
                    tg_user.username
                    if tg_user and tg_user.username is not None
                    else chat_username
                ),
                "first_name": (
                    tg_user.first_name
                    if tg_user and tg_user.first_name is not None
                    else getattr(chat, "first_name", None)
                ),
                "last_name": (
                    tg_user.last_name
                    if tg_user and tg_user.last_name is not None
                    else getattr(chat, "last_name", None)
                ),
            }

        return {
            "chat_type": chat_type,
            "chat_title": chat_title,
            "username": chat_username,
            "first_name": None,
            "last_name": None,
        }
