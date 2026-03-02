import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.models.file import FileStorageRef
from giga_agent.models.sandbox import SandboxProviderSnapshot, SandboxSnapshot
from giga_agent.sandbox.cleanup_tasks import cleanup_storage_files_best_effort


class CleanupTasksTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_skips_when_provider_snapshot_missing(self):
        ref = FileStorageRef(
            owner_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            sandbox_path="/bucket/giga_agent/u/a.txt",
        )

        with patch(
            "giga_agent.sandbox.cleanup_tasks.SandboxRuntimeFactory.build",
            return_value=types.SimpleNamespace(delete_file=AsyncMock(return_value=None)),
        ) as mocked_build, patch(
            "giga_agent.sandbox.cleanup_tasks.logger.warning"
        ) as mocked_warning:
            await cleanup_storage_files_best_effort([ref])

        mocked_build.assert_not_called()
        mocked_warning.assert_called()

    async def test_cleanup_deletes_when_snapshots_are_provided(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        ref = FileStorageRef(
            owner_id=owner_id,
            provider_id=provider_id,
            sandbox_path="/bucket/giga_agent/u/a.txt",
        )
        provider_snapshot = SandboxProviderSnapshot(
            id=provider_id,
            owner_id=owner_id,
            type="e2b",
            name="main",
            settings={},
            idle_timeout=3600,
            is_active=True,
        )
        sandbox_snapshot = SandboxSnapshot(
            id=uuid.uuid4(),
            owner_id=owner_id,
            provider_id=provider_id,
            status="stopped",
            settings={},
        )
        runtime = types.SimpleNamespace(delete_file=AsyncMock(return_value=None))

        with patch(
            "giga_agent.sandbox.cleanup_tasks.SandboxRuntimeFactory.build",
            return_value=runtime,
        ) as mocked_build:
            await cleanup_storage_files_best_effort(
                [ref],
                provider_snapshot=provider_snapshot,
                sandbox_snapshots_by_owner={str(owner_id): sandbox_snapshot},
            )

        mocked_build.assert_called_once()
        runtime.delete_file.assert_awaited_once_with(ref.sandbox_path)
