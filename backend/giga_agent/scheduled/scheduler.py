from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from cashews import cache
from cashews.exceptions import LockedError

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.scheduled_task import ScheduledTaskRepository
from giga_agent.scheduled.runner import execute_due_task

logger = get_logger(__name__)


class ScheduledTaskScheduler:
    """Background sweeper that runs due scheduled tasks and delivers results.

    Correctness does not depend on the lock: ``claim_due`` claims each task with
    a conditional UPDATE (rowcount==1), so a row is handed to exactly one worker
    even across processes. The cashews lock is an optimization that stops several
    workers from scanning/claiming the same batch in lock-step. Claimed tasks
    (status -> running) are processed outside the lock so long agent runs don't
    hold it past its TTL.
    """

    def __init__(
        self,
        *,
        interval_sec: int,
        lock_key: str,
        lock_ttl_sec: int,
        run_timeout_sec: int,
        max_concurrent_runs: int,
        enabled: bool = True,
    ) -> None:
        self.interval_sec = interval_sec
        self.lock_key = lock_key
        self.lock_ttl_sec = lock_ttl_sec
        self.run_timeout_sec = run_timeout_sec
        self.max_concurrent_runs = max_concurrent_runs
        self.enabled = enabled
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled:
            logger.info("Scheduled task scheduler is disabled")
            return
        if self._task is not None and not self._task.done():
            return
        logger.info(
            "Starting scheduled task scheduler (interval=%ss, lock_key=%s)",
            self.interval_sec,
            self.lock_key,
        )
        self._task = asyncio.create_task(
            self._run_forever(),
            name="scheduled-task-scheduler",
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def reset_stale(self) -> None:
        """Reset tasks stuck in running (e.g. after a process restart)."""
        try:
            session_factory = await get_session_factory()
            async with session_factory() as session:
                count = await ScheduledTaskRepository(session).reset_stale_running()
                if count:
                    logger.info("Reset %s stale running scheduled task(s)", count)
        except Exception:
            logger.exception("Failed to reset stale scheduled tasks")

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled task scheduler iteration failed")

            try:
                await asyncio.sleep(self.interval_sec)
            except asyncio.CancelledError:
                raise

    async def _claim_due_ids(self) -> list:
        """Acquire the lock, claim due tasks, release. Returns claimed task ids."""
        session_factory = await get_session_factory()
        async with session_factory() as session:
            try:
                async with cache.lock(
                    self.lock_key,
                    expire=self.lock_ttl_sec,
                    wait=False,
                ):
                    repo = ScheduledTaskRepository(session)
                    now = datetime.now(timezone.utc)
                    tasks = await repo.claim_due(now)
                    return [task.id for task in tasks]
            except LockedError:
                logger.debug("Scheduler tick skipped: lock is busy")
                return []

    async def _run_once(self) -> None:
        task_ids = await self._claim_due_ids()
        if not task_ids:
            return

        logger.info("Scheduler claimed %s due task(s)", len(task_ids))
        semaphore = asyncio.Semaphore(self.max_concurrent_runs)

        async def _process(task_id) -> None:
            async with semaphore:
                try:
                    await execute_due_task(task_id, run_timeout=self.run_timeout_sec)
                except Exception:
                    logger.exception("Scheduled task %s processing failed", task_id)

        await asyncio.gather(*[_process(tid) for tid in task_ids])
