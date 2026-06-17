"""Shared runtime helpers for Telegram channel instances."""

from __future__ import annotations

from aiogram import types as tg_types

from giga_agent.models.channel import ChannelBot


def get_bot_token(bot_row: ChannelBot) -> str:
    legacy_token = getattr(bot_row, "bot_token", None)
    if isinstance(legacy_token, str) and legacy_token.strip():
        return legacy_token
    token = (bot_row.settings or {}).get("bot_token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Telegram channel settings must include a non-empty bot_token")
    return token


def get_bot_username(bot_row: ChannelBot) -> str | None:
    username = bot_row.bot_username
    if isinstance(username, str) and username.strip():
        return username
    return None


def get_contact_external_user_id(_: tg_types.Message) -> str | None:
    # Contacts/approvals remain chat-scoped for compatibility with the UI/API.
    return None


def get_thread_external_user_id(message: tg_types.Message) -> str | None:
    chat_type = getattr(message.chat, "type", None)
    if chat_type == "private":
        return None
    if message.from_user is None:
        return None
    return str(message.from_user.id)


def build_memory_tags(message: tg_types.Message) -> list[str]:
    """Scope memory by chat (private → tg_user_<id>, group → tg_chat_<id>)."""
    chat = message.chat
    chat_type = getattr(chat, "type", None)
    if chat_type == "private":
        user = message.from_user
        if user is not None:
            return [f"tg_user_{user.id}"]
        return [f"tg_chat_{chat.id}"]
    return [f"tg_chat_{chat.id}"]
