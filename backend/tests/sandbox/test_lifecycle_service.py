import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch, Mock

from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.manager.errors import StorageOperationError
from giga_agent.sandbox.manager.lifecycle_service import SandboxLifecycleService


class SandboxLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = SandboxLifecycleService(db=types.SimpleNamespace())
        self.service._sandbox_repo = types.SimpleNamespace(
            get_by_id_with_provider=AsyncMock(),
            set_status=AsyncMock(side_effect=self._set_status),
            get_stale_starting_sandboxes=AsyncMock(),
        )

    async def _set_status(self, sandbox, status):
        sandbox.status = status
        return sandbox

    @staticmethod
    def _sandbox(*, status: SandboxStatus) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            provider=types.SimpleNamespace(),
            status=status,
            settings={"host_port": 1234, "keep": "yes"},
            external_id="ext-1",
        )

    async def test_stop_transitional_runtime_stop_failure_sets_stopped_if_runtime_down(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            stop=AsyncMock(side_effect=RuntimeError("daemon down")),
            is_up=AsyncMock(return_value=False),
            get_connection_settings=lambda: {"external_id": "ext-1", "host_port": 1234},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ) as mocked_invalidate:
            result = await self.service._stop_unlocked(sandbox.id)

        self.assertIs(result, sandbox)
        self.assertEqual(sandbox.status, SandboxStatus.STOPPED)
        self.assertEqual(sandbox.settings, {"keep": "yes"})
        self.assertIsNone(sandbox.external_id)
        statuses = [
            call.args[1]
            for call in self.service._sandbox_repo.set_status.await_args_list
        ]
        self.assertEqual(statuses, [SandboxStatus.STOPPING, SandboxStatus.STOPPED])
        mocked_invalidate.assert_awaited_once_with(
            owner_id=sandbox.owner_id,
            provider_id=sandbox.provider_id,
        )

    async def test_stop_transitional_runtime_stop_failure_sets_error_if_runtime_still_up(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            stop=AsyncMock(side_effect=RuntimeError("daemon down")),
            is_up=AsyncMock(return_value=True),
            get_connection_settings=lambda: {"external_id": "ext-1", "host_port": 1234},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(StorageOperationError):
                await self.service._stop_unlocked(sandbox.id)

        self.assertEqual(sandbox.status, SandboxStatus.ERROR)
        statuses = [
            call.args[1]
            for call in self.service._sandbox_repo.set_status.await_args_list
        ]
        self.assertEqual(statuses, [SandboxStatus.STOPPING, SandboxStatus.ERROR])

    async def test_stop_transitional_runtime_stop_failure_sets_error_if_probe_fails(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            stop=AsyncMock(side_effect=RuntimeError("daemon down")),
            is_up=AsyncMock(side_effect=RuntimeError("probe failed")),
            get_connection_settings=lambda: {"external_id": "ext-1", "host_port": 1234},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(StorageOperationError):
                await self.service._stop_unlocked(sandbox.id)

        self.assertEqual(sandbox.status, SandboxStatus.ERROR)
        statuses = [
            call.args[1]
            for call in self.service._sandbox_repo.set_status.await_args_list
        ]
        self.assertEqual(statuses, [SandboxStatus.STOPPING, SandboxStatus.ERROR])

    async def test_stop_running_runtime_stop_failure_sets_error(self):
        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        runtime = types.SimpleNamespace(
            stop=AsyncMock(side_effect=RuntimeError("daemon down")),
            get_connection_settings=lambda: {"external_id": "ext-1"},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(StorageOperationError):
                await self.service._stop_unlocked(sandbox.id)

        self.assertEqual(sandbox.status, SandboxStatus.ERROR)
        statuses = [
            call.args[1]
            for call in self.service._sandbox_repo.set_status.await_args_list
        ]
        self.assertEqual(statuses, [SandboxStatus.STOPPING, SandboxStatus.ERROR])

    async def test_reconcile_stale_starting_promotes_to_running_when_runtime_up(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            is_up=AsyncMock(return_value=True),
            get_connection_settings=lambda: {"external_id": "ext-1"},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            reconciled = await self.service._reconcile_stale_starting_unlocked(
                sandbox.id
            )

        self.assertEqual(reconciled, sandbox.id)
        self.assertEqual(sandbox.status, SandboxStatus.RUNNING)

    async def test_reconcile_stale_starting_heals_to_stopped_when_runtime_down(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            is_up=AsyncMock(return_value=False),
            get_connection_settings=lambda: {"external_id": "ext-1", "host_port": 1234},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            reconciled = await self.service._reconcile_stale_starting_unlocked(
                sandbox.id
            )

        self.assertEqual(reconciled, sandbox.id)
        self.assertEqual(sandbox.status, SandboxStatus.STOPPED)
        self.assertEqual(sandbox.settings, {"keep": "yes"})
        self.assertIsNone(sandbox.external_id)

    async def test_reconcile_stale_starting_handles_probe_exception_as_stopped(self):
        sandbox = self._sandbox(status=SandboxStatus.STARTING)
        runtime = types.SimpleNamespace(
            is_up=AsyncMock(side_effect=RuntimeError("provider unavailable")),
            get_connection_settings=lambda: {"external_id": "ext-1"},
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            reconciled = await self.service._reconcile_stale_starting_unlocked(
                sandbox.id
            )

        self.assertEqual(reconciled, sandbox.id)
        self.assertEqual(sandbox.status, SandboxStatus.STOPPED)

    async def test_reconcile_stale_starting_skips_when_status_changed(self):
        sandbox = self._sandbox(status=SandboxStatus.STOPPED)
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )

        reconciled = await self.service._reconcile_stale_starting_unlocked(sandbox.id)

        self.assertIsNone(reconciled)

    async def test_reconcile_stale_starting_queries_repo_by_ttl(self):
        stale = self._sandbox(status=SandboxStatus.STARTING)
        self.service._sandbox_repo.get_stale_starting_sandboxes = AsyncMock(
            return_value=[stale]
        )
        self.service._with_lifecycle_lock = AsyncMock(return_value=stale.id)  # type: ignore[method-assign]

        reconciled = await self.service.reconcile_stale_starting(120)

        self.assertEqual(reconciled, [stale.id])
        self.service._sandbox_repo.get_stale_starting_sandboxes.assert_awaited_once()
        stale_before = (
            self.service._sandbox_repo.get_stale_starting_sandboxes.await_args.kwargs[
                "stale_before"
            ]
        )
        self.assertIsInstance(stale_before, datetime)
