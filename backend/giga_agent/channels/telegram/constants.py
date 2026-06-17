"""Shared constants for the Telegram runtime."""

from __future__ import annotations

ASSISTANT_ID = "giga_agent_channel"
THREAD_TTL_SECONDS = 24 * 60 * 60
MESSAGE_TOOL_CALLBACK_PREFIX = "ga_msg:"
SUPPORTED_CHAT_TYPES = {"private", "group", "supergroup"}
GROUP_CHAT_TYPES = {"group", "supergroup"}
TELEGRAM_CHANNEL_TYPE = "telegram"
