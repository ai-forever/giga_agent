"""Telegram integration module for GigaAgent."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from giga_agent.core.module import BaseModule
from giga_agent.core.logging import get_logger
from giga_agent.modules.telegram.models import (
    TelegramBot,
    TelegramContact,
    TelegramThread,
)

if TYPE_CHECKING:
    from fastapi import APIRouter
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class TelegramModule(BaseModule):
    id: str = "telegram"

    def get_api_router(self, **kwargs: Any) -> "APIRouter":
        from giga_agent.modules.telegram.api import router

        return router

    def get_models(self, **kwargs: Any) -> list[type]:
        return [TelegramBot, TelegramContact, TelegramThread]

    async def on_startup(self, session: "AsyncSession", **kwargs: Any):
        from giga_agent.modules.telegram.manager import get_bot_manager

        manager = get_bot_manager()
        try:
            await manager.start_all()
        except Exception:
            logger.exception("Failed to start Telegram bots on startup")
