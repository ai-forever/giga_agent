import asyncio
import types
import unittest
from unittest.mock import AsyncMock, patch

from cashews.exceptions import LockedError

from giga_agent.sandbox.orphan_sweeper import OrphanSandboxSweeper


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
        raise LockedError("Key sandbox:orphan-cleanup:lock is already locked")

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class OrphanSandboxSweeperTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_cleans_orphans_when_lock_is_free(self):
        sweeper = OrphanSandboxSweeper(
            interval_sec=120,
            lock_key="sandbox:orphan-cleanup:lock",
            lock_ttl_sec=110,
            concurrency=2,
            enabled=True,
        )
        session = object()
        manager = types.SimpleNamespace(
            cleanup_orphans=AsyncMock(return_value={"local_docker": ["sandbox-1"]})
        )

        with (
            patch(
                "giga_agent.sandbox.orphan_sweeper.get_session_factory",
                AsyncMock(return_value=lambda: _SessionContext(session)),
            ),
            patch(
                "giga_agent.sandbox.orphan_sweeper.cache.lock",
                return_value=_NoopLock(),
            ) as lock_mock,
            patch(
                "giga_agent.sandbox.orphan_sweeper.SandboxManager",
                return_value=manager,
            ) as manager_cls,
        ):
            await sweeper._run_once()

        lock_mock.assert_called_once_with(
            "sandbox:orphan-cleanup:lock",
            expire=110,
            wait=False,
        )
        manager_cls.assert_called_once_with(session)
        manager.cleanup_orphans.assert_awaited_once_with(concurrency=2)

    async def test_run_once_skips_when_lock_is_busy(self):
        sweeper = OrphanSandboxSweeper(
            interval_sec=120,
            lock_key="sandbox:orphan-cleanup:lock",
            lock_ttl_sec=110,
            concurrency=2,
            enabled=True,
        )
        session = object()

        with (
            patch(
                "giga_agent.sandbox.orphan_sweeper.get_session_factory",
                AsyncMock(return_value=lambda: _SessionContext(session)),
            ),
            patch(
                "giga_agent.sandbox.orphan_sweeper.cache.lock",
                return_value=_RaiseLockedOnEnter(),
            ) as lock_mock,
            patch(
                "giga_agent.sandbox.orphan_sweeper.SandboxManager",
            ) as manager_cls,
        ):
            await sweeper._run_once()

        lock_mock.assert_called_once_with(
            "sandbox:orphan-cleanup:lock",
            expire=110,
            wait=False,
        )
        manager_cls.assert_not_called()

    async def test_run_forever_continues_after_iteration_error(self):
        sweeper = OrphanSandboxSweeper(
            interval_sec=120,
            lock_key="sandbox:orphan-cleanup:lock",
            lock_ttl_sec=110,
            concurrency=2,
            enabled=True,
        )
        sweeper._run_once = AsyncMock(  # type: ignore[method-assign]
            side_effect=[RuntimeError("boom"), None, asyncio.CancelledError()]
        )

        with (
            patch(
                "giga_agent.sandbox.orphan_sweeper.asyncio.sleep",
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await sweeper._run_forever()

        self.assertEqual(sweeper._run_once.await_count, 3)
