from __future__ import annotations

import asyncio
from contextlib import suppress

from cashews import cache
from cashews.exceptions import LockedError

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.sandbox.manager import SandboxManager

logger = get_logger(__name__)


class OrphanSandboxSweeper:
    def __init__(
        self,
        *,
        interval_sec: int,
        lock_key: str,
        lock_ttl_sec: int,
        concurrency: int,
        enabled: bool = True,
    ) -> None:
        self.interval_sec = interval_sec
        self.lock_key = lock_key
        self.lock_ttl_sec = lock_ttl_sec
        self.concurrency = concurrency
        self.enabled = enabled
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled:
            logger.info("Orphan sandbox sweeper is disabled")
            return
        if self._task is not None and not self._task.done():
            return
        logger.info(
            "Starting orphan sandbox sweeper (interval=%ss, lock_key=%s, lock_ttl=%ss, concurrency=%s)",
            self.interval_sec,
            self.lock_key,
            self.lock_ttl_sec,
            self.concurrency,
        )
        self._task = asyncio.create_task(
            self._run_forever(),
            name="orphan-sandbox-sweeper",
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Orphan sandbox sweeper iteration failed")

            try:
                await asyncio.sleep(self.interval_sec)
            except asyncio.CancelledError:
                raise

    async def _run_once(self) -> None:
        session_factory = await get_session_factory()
        async with session_factory() as session:
            try:
                async with cache.lock(
                    self.lock_key,
                    expire=self.lock_ttl_sec,
                    wait=False,
                ):
                    manager = SandboxManager(session)
                    cleaned = await manager.cleanup_orphans(
                        concurrency=self.concurrency
                    )
                    if cleaned:
                        logger.info(
                            "Orphan sandbox sweeper applied cleanup for provider types: %s",
                            sorted(cleaned.keys()),
                        )
            except LockedError:
                logger.debug("Orphan sandbox cleanup skipped: lock is busy")
                return
            except Exception:
                logger.exception("Orphan sandbox cleanup failed")
                return
