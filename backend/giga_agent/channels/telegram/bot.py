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


def create_telegram_bot(token: str) -> Bot:
    proxy = _get_env_proxy("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY")
    if proxy:
        logger.info("Telegram bot session proxy enabled")
        return Bot(token=token, session=AiohttpSession(proxy=proxy))
    return Bot(token=token)

__all__ = ["create_telegram_bot"]
