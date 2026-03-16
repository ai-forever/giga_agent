import asyncio
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from cashews.exceptions import LockedError

from giga_agent.conf import GIGA_AGENT_SANDBOX_STARTING_TTL_SEC
from giga_agent.sandbox.idle_sweeper import IdleSandboxSweeper


class _SessionContext:
    def __init__(self, session: object):
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _NoopLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _RaiseLockedOnEnter:
    async def __aenter__(self) -> None:
        raise LockedError("Key sandbox:idle-cleanup:lock is already locked")

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class IdleSandboxSweeperTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_stops_idle_sandboxes_when_lock_is_free(self):
        sweeper = IdleSandboxSweeper(
            interval_sec=60,
            lock_key="sandbox:idle-cleanup:lock",
            lock_ttl_sec=55,
            enabled=True,
        )
        session = object()
        manager = types.SimpleNamespace(
            stop_idle_sandboxes=AsyncMock(return_value=[uuid.uuid4()]),
            reconcile_stale_starting_sandboxes=AsyncMock(return_value=[uuid.uuid4()]),
        )

        with (
            patch(
                "giga_agent.sandbox.idle_sweeper.get_session_factory",
                AsyncMock(return_value=lambda: _SessionContext(session)),
            ),
            patch(
                "giga_agent.sandbox.idle_sweeper.cache.lock",
                return_value=_NoopLock(),
            ) as lock_mock,
            patch(
                "giga_agent.sandbox.idle_sweeper.SandboxManager",
                return_value=manager,
            ) as manager_cls,
        ):
            await sweeper._run_once()

        lock_mock.assert_called_once_with(
            "sandbox:idle-cleanup:lock",
            expire=55,
            wait=False,
        )
        manager_cls.assert_called_once_with(session)
        manager.stop_idle_sandboxes.assert_awaited_once()
        manager.reconcile_stale_starting_sandboxes.assert_awaited_once_with(
            GIGA_AGENT_SANDBOX_STARTING_TTL_SEC
        )

    async def test_run_once_skips_when_lock_is_busy(self):
        sweeper = IdleSandboxSweeper(
            interval_sec=60,
            lock_key="sandbox:idle-cleanup:lock",
            lock_ttl_sec=55,
            enabled=True,
        )
        session = object()

        with (
            patch(
                "giga_agent.sandbox.idle_sweeper.get_session_factory",
                AsyncMock(return_value=lambda: _SessionContext(session)),
            ),
            patch(
                "giga_agent.sandbox.idle_sweeper.cache.lock",
                return_value=_RaiseLockedOnEnter(),
            ) as lock_mock,
            patch(
                "giga_agent.sandbox.idle_sweeper.SandboxManager",
            ) as manager_cls,
        ):
            await sweeper._run_once()

        lock_mock.assert_called_once_with(
            "sandbox:idle-cleanup:lock",
            expire=55,
            wait=False,
        )
        manager_cls.assert_not_called()

    async def test_run_forever_continues_after_iteration_error(self):
        sweeper = IdleSandboxSweeper(
            interval_sec=60,
            lock_key="sandbox:idle-cleanup:lock",
            lock_ttl_sec=55,
            enabled=True,
        )
        sweeper._run_once = AsyncMock(  # type: ignore[method-assign]
            side_effect=[RuntimeError("boom"), None, asyncio.CancelledError()]
        )

        with (
            patch(
                "giga_agent.sandbox.idle_sweeper.asyncio.sleep",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await sweeper._run_forever()

        self.assertEqual(sweeper._run_once.await_count, 3)

    async def test_start_and_stop_manage_background_task(self):
        sweeper = IdleSandboxSweeper(
            interval_sec=60,
            lock_key="sandbox:idle-cleanup:lock",
            lock_ttl_sec=55,
            enabled=True,
        )
        sweeper._run_once = AsyncMock(return_value=None)  # type: ignore[method-assign]

        sweeper.start()
        task = sweeper._task
        self.assertIsNotNone(task)

        sweeper.start()
        self.assertIs(task, sweeper._task)

        await sweeper.stop()
        self.assertIsNone(sweeper._task)
        assert task is not None
        self.assertTrue(task.done())
