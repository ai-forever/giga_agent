"""Lifecycle manager for active channel runtime instances."""

from __future__ import annotations

import uuid

from giga_agent.channels.base import Channel
from giga_agent.channels.registry import ChannelRegistry
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot, ChannelBotRepository

# Ensure runtime registrations are loaded before manager startup.
import giga_agent.channels  # noqa: F401

logger = get_logger(__name__)


class ChannelManager:
    def __init__(self):
        self._runtimes: dict[uuid.UUID, tuple[ChannelBot, Channel]] = {}

    async def start_all(self) -> None:
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = ChannelBotRepository(session)
            bots = await repo.get_all_enabled()
            for bot_row in bots:
                await self._start_bot(bot_row)

    async def _start_bot(self, bot_row: ChannelBot) -> None:
        if bot_row.id in self._runtimes:
            return

        try:
            runtime = await ChannelRegistry.get_runtime(
                bot_row.channel_type,
                bot_row.settings or {},
            )
            await runtime.start(bot_row)
            self._runtimes[bot_row.id] = (bot_row, runtime)
        except Exception:
            logger.exception(
                "Failed to start %s channel bot %s",
                bot_row.channel_type,
                bot_row.id,
            )

    async def start_bot(self, bot_id: uuid.UUID) -> None:
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = ChannelBotRepository(session)
            bot_row = await repo.get_by_id(bot_id)
            if bot_row and bot_row.is_enabled:
                await self._start_bot(bot_row)

    async def stop_bot(self, bot_id: uuid.UUID) -> None:
        active = self._runtimes.pop(bot_id, None)
        if active is None:
            return

        bot_row, runtime = active
        try:
            await runtime.stop(bot_row)
        except Exception:
            logger.exception(
                "Failed to stop %s channel bot %s",
                bot_row.channel_type,
                bot_row.id,
            )

    async def restart_bot(self, bot_id: uuid.UUID) -> None:
        await self.stop_bot(bot_id)
        await self.start_bot(bot_id)

    async def stop_all(self) -> None:
        for bot_id in list(self._runtimes.keys()):
            await self.stop_bot(bot_id)

    def is_running(self, bot_id: uuid.UUID) -> bool:
        return bot_id in self._runtimes


_manager: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    global _manager
    if _manager is None:
        _manager = ChannelManager()
    return _manager
