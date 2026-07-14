import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch, Mock

from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.local_docker import LocalDockerSandbox
from giga_agent.sandbox.manager.errors import StorageOperationError
from giga_agent.sandbox.manager.lifecycle_service import SandboxLifecycleService
from giga_agent.sandbox.manager.types import (
    RemoveExternalRuntimeAction,
    SetSandboxStatusAction,
)


class SandboxLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = SandboxLifecycleService(db=types.SimpleNamespace())
        self.service._sandbox_repo = types.SimpleNamespace(
            get_by_id_with_provider=AsyncMock(),
            set_status=AsyncMock(side_effect=self._set_status),
            get_stale_starting_sandboxes=AsyncMock(),
            get_by_provider_type_with_provider=AsyncMock(return_value=[]),
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

    async def test_ensure_running_for_user_reuses_running_runtime_when_liveness_probe_succeeds(
        self,
    ):
        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        sandbox.provider = types.SimpleNamespace(type="local_docker")
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)
        resolved = types.SimpleNamespace(sandbox=sandbox)
        self.service._resolve = types.SimpleNamespace(
            get_or_create_for_user=AsyncMock(return_value=resolved)
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(return_value=sandbox)
        self.service._sandbox_repo.touch = AsyncMock()
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )

        async def _run(_sandbox_id, action):
            return await action()

        self.service._with_lifecycle_lock = AsyncMock(side_effect=_run)  # type: ignore[method-assign]

        with patch.object(
            LocalDockerSandbox,
            "is_up",
            AsyncMock(return_value=True),
        ) as is_up_mock:
            result = await self.service.ensure_running_for_user(
                user_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        self.assertIs(result, runtime)
        is_up_mock.assert_awaited_once()
        self.service._sandbox_repo.touch.assert_awaited_once_with(sandbox.id)

    async def test_ensure_running_for_user_restarts_runtime_when_liveness_probe_fails(
        self,
    ):
        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        sandbox.provider = types.SimpleNamespace(type="local_docker")
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)
            restarted_runtime = LocalDockerSandbox(max_active_sandboxes=1)
        resolved = types.SimpleNamespace(sandbox=sandbox)
        self.service._resolve = types.SimpleNamespace(
            get_or_create_for_user=AsyncMock(return_value=resolved)
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(return_value=sandbox)
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )
        self.service._stop_runtime_for_sandbox = AsyncMock(return_value=sandbox)  # type: ignore[method-assign]
        self.service._start_unlocked = AsyncMock(return_value=restarted_runtime)  # type: ignore[method-assign]

        async def _run(_sandbox_id, action):
            return await action()

        self.service._with_lifecycle_lock = AsyncMock(side_effect=_run)  # type: ignore[method-assign]

        with patch.object(
            LocalDockerSandbox,
            "is_up",
            AsyncMock(return_value=False),
        ) as is_up_mock:
            result = await self.service.ensure_running_for_user(
                user_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        self.assertIs(result, restarted_runtime)
        is_up_mock.assert_awaited_once()
        self.service._stop_runtime_for_sandbox.assert_awaited_once()
        self.service._start_unlocked.assert_awaited_once_with(sandbox.id)

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

    async def test_start_failure_runs_best_effort_runtime_cleanup(self):
        sandbox = self._sandbox(status=SandboxStatus.STOPPED)
        runtime = types.SimpleNamespace(
            up=AsyncMock(side_effect=RuntimeError("boom")),
            stop=AsyncMock(return_value=None),
            get_connection_settings=lambda: {"external_id": "ext-1"},
            has_limit=lambda: False,
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(return_value=sandbox)
        self.service._runtime_factory = types.SimpleNamespace(build=Mock(return_value=runtime))

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(StorageOperationError):
                await self.service._start_unlocked(sandbox.id)

        runtime.stop.assert_awaited_once()

    async def test_apply_remove_orphan_action_calls_runtime_remove(self):
        removed: list[str] = []

        class _Runtime:
            @classmethod
            async def remove_external_runtime(cls, external_id: str) -> None:
                removed.append(external_id)

        action = RemoveExternalRuntimeAction(
            provider_type="local_docker",
            provider_id=uuid.uuid4(),
            sandbox_id=None,
            external_id="ext-1",
            reason="test",
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRegistry.get",
            return_value=_Runtime,
        ):
            result = await self.service.apply_orphan_action(action)

        self.assertEqual(result, "ext-1")
        self.assertEqual(removed, ["ext-1"])

    async def test_apply_set_status_action_clears_runtime_connection_state(self):
        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        runtime = types.SimpleNamespace(
            get_connection_settings=lambda: {"external_id": "ext-1", "host_port": 1234}
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(return_value=sandbox)
        self.service._runtime_factory = types.SimpleNamespace(build=Mock(return_value=runtime))
        async def _run(_sandbox_id, action):
            return await action()
        self.service._with_lifecycle_lock = AsyncMock(side_effect=_run)  # type: ignore[method-assign]
        action = SetSandboxStatusAction(
            provider_type="local_docker",
            provider_id=sandbox.provider_id,
            sandbox_id=sandbox.id,
            status=SandboxStatus.STOPPED,
            reason="missing_container",
            clear_runtime_connection=True,
        )

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            result = await self.service.apply_orphan_action(action)

        self.assertEqual(result, str(sandbox.id))
        self.assertEqual(sandbox.status, SandboxStatus.STOPPED)
        self.assertEqual(sandbox.settings, {"keep": "yes"})
        self.assertIsNone(sandbox.external_id)


    async def test_recreate_unlocked_force_removes_and_restarts(self):
        sandbox = self._sandbox(status=SandboxStatus.RUNNING)

        class _FakeRuntime:
            removed: list = []

            def __init__(self):
                self.stop = AsyncMock()

            def get_connection_settings(self):
                return {"external_id": "ext-1", "host_port": 1234}

            @classmethod
            async def remove_external_runtime(cls, external_id):
                cls.removed.append(external_id)

        runtime = _FakeRuntime()
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )
        started = types.SimpleNamespace(name="fresh-runtime")
        self.service._start_unlocked = AsyncMock(return_value=started)  # type: ignore[method-assign]

        with patch(
            "giga_agent.sandbox.manager.lifecycle_service.SandboxRepository.cache_invalidate_pair",
            AsyncMock(return_value=None),
        ):
            result = await self.service._recreate_unlocked(
                sandbox, reason="provider_settings_recreate"
            )

        self.assertIs(result, started)
        # контейнер принудительно удалён (даже если бы был not_remove)
        self.assertIn("ext-1", _FakeRuntime.removed)
        runtime.stop.assert_awaited_once()
        # connection-state вычищен, но пользовательские ключи сохранены
        self.assertEqual(sandbox.settings, {"keep": "yes"})
        self.assertIsNone(sandbox.external_id)
        statuses = [
            call.args[1]
            for call in self.service._sandbox_repo.set_status.await_args_list
        ]
        self.assertEqual(statuses, [SandboxStatus.STOPPING, SandboxStatus.STOPPED])
        self.service._start_unlocked.assert_awaited_once_with(sandbox.id)

    def _running_local_runtime(self):
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            return LocalDockerSandbox(max_active_sandboxes=1)

    async def test_ensure_running_recreates_on_cold_settings_change(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        sandbox.provider = types.SimpleNamespace(type="local_docker")
        runtime = self._running_local_runtime()
        resolved = types.SimpleNamespace(sandbox=sandbox)
        self.service._resolve = types.SimpleNamespace(
            get_or_create_for_user=AsyncMock(return_value=resolved)
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._sandbox_repo.touch = AsyncMock()
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )
        recreated = self._running_local_runtime()
        self.service._recreate_unlocked = AsyncMock(return_value=recreated)  # type: ignore[method-assign]

        async def _run(_sandbox_id, action):
            return await action()

        self.service._with_lifecycle_lock = AsyncMock(side_effect=_run)  # type: ignore[method-assign]

        with patch.object(
            LocalDockerSandbox, "is_up", AsyncMock(return_value=True)
        ), patch.object(
            LocalDockerSandbox,
            "reconcile_runtime_settings",
            AsyncMock(return_value=RuntimeReconcileOutcome.RECREATE),
        ):
            result = await self.service.ensure_running_for_user(
                user_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        self.assertIs(result, recreated)
        self.service._recreate_unlocked.assert_awaited_once()
        self.service._sandbox_repo.touch.assert_not_awaited()

    async def test_ensure_running_touches_and_reuses_on_hot_update(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        sandbox = self._sandbox(status=SandboxStatus.RUNNING)
        sandbox.provider = types.SimpleNamespace(type="local_docker")
        runtime = self._running_local_runtime()
        resolved = types.SimpleNamespace(sandbox=sandbox)
        self.service._resolve = types.SimpleNamespace(
            get_or_create_for_user=AsyncMock(return_value=resolved)
        )
        self.service._sandbox_repo.get_by_id_with_provider = AsyncMock(
            return_value=sandbox
        )
        self.service._sandbox_repo.touch = AsyncMock()
        self.service._runtime_factory = types.SimpleNamespace(
            build=Mock(return_value=runtime)
        )
        self.service._recreate_unlocked = AsyncMock()  # type: ignore[method-assign]

        async def _run(_sandbox_id, action):
            return await action()

        self.service._with_lifecycle_lock = AsyncMock(side_effect=_run)  # type: ignore[method-assign]

        with patch.object(
            LocalDockerSandbox, "is_up", AsyncMock(return_value=True)
        ), patch.object(
            LocalDockerSandbox,
            "reconcile_runtime_settings",
            AsyncMock(return_value=RuntimeReconcileOutcome.HOT_UPDATED),
        ):
            result = await self.service.ensure_running_for_user(
                user_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        self.assertIs(result, runtime)
        self.service._sandbox_repo.touch.assert_awaited_once_with(sandbox.id)
        self.service._recreate_unlocked.assert_not_awaited()
