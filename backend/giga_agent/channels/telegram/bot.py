"""Telegram bot construction helpers."""

from __future__ import annotations

import os

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def _get_env_proxy(*names: str) -> str | None:
    for name in names:
        value = (os.getenv(name) or os.getenv(name.lower()) or "").strip()
        if value:
            return value
    return None


def _normalize_aiogram_proxy(proxy: str) -> str:
    normalized = proxy.strip()
    if normalized.lower().startswith("socks5h://"):
        logger.info("Normalizing Telegram proxy scheme from socks5h to socks5")
        return "socks5://" + normalized[len("socks5h://") :]
    return normalized


def create_telegram_bot(token: str, *, bot_row=None) -> Bot:
    proxy = _get_env_proxy("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY")
    if proxy:
        logger.info("Telegram bot session proxy enabled")
        bot = Bot(
            token=token, session=AiohttpSession(proxy=_normalize_aiogram_proxy(proxy))
        )
    else:
        bot = Bot(token=token)
    if bot_row is not None:
        from functools import partial

        from giga_agent.channels.telegram.chat_history import archive_outgoing_request

        bot.session.middleware.register(
            partial(archive_outgoing_request, bot_row=bot_row)
        )
    return bot


__all__ = ["create_telegram_bot"]
