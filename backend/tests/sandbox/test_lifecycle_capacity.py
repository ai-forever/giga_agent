import types
import unittest
import uuid
from unittest.mock import AsyncMock

from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.manager.errors import SandboxBusyError
from giga_agent.sandbox.manager.lifecycle_service import SandboxLifecycleService


class SandboxLifecycleCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = SandboxLifecycleService(db=types.SimpleNamespace())
        self.service._sandbox_repo = types.SimpleNamespace(
            count_by_provider_and_statuses=AsyncMock(),
            set_status=AsyncMock(),
        )
        async def _run(provider_id, action):
            await action()
        self.service._with_provider_capacity_lock = AsyncMock(side_effect=_run)

    async def test_reserve_capacity_skips_check_for_unlimited_runtime(self):
        sandbox = types.SimpleNamespace(provider_id=uuid.uuid4())
        runtime = types.SimpleNamespace(has_limit=lambda: False)

        await self.service._reserve_capacity_and_mark_starting(
            sandbox=sandbox,
            runtime=runtime,
        )

        self.service._sandbox_repo.set_status.assert_awaited_once_with(
            sandbox,
            SandboxStatus.STARTING,
        )
        self.service._sandbox_repo.count_by_provider_and_statuses.assert_not_called()

    async def test_reserve_capacity_raises_when_limit_exceeded(self):
        sandbox = types.SimpleNamespace(provider_id=uuid.uuid4())
        runtime = types.SimpleNamespace(has_limit=lambda: True, max_active_sandboxes=2)

        self.service._sandbox_repo.count_by_provider_and_statuses = AsyncMock(return_value=2)

        with self.assertRaises(SandboxBusyError):
            await self.service._reserve_capacity_and_mark_starting(
                sandbox=sandbox,
                runtime=runtime,
            )

        self.service._sandbox_repo.set_status.assert_not_called()

    async def test_reserve_capacity_marks_starting_when_slot_available(self):
        sandbox = types.SimpleNamespace(provider_id=uuid.uuid4())
        runtime = types.SimpleNamespace(has_limit=lambda: True, max_active_sandboxes=3)

        self.service._sandbox_repo.count_by_provider_and_statuses = AsyncMock(return_value=2)

        await self.service._reserve_capacity_and_mark_starting(
            sandbox=sandbox,
            runtime=runtime,
        )

        self.service._sandbox_repo.set_status.assert_awaited_once_with(
            sandbox,
            SandboxStatus.STARTING,
        )
