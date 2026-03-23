import os
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.local_jupyter.dependencies import MissingDependenciesError
from giga_agent.sandbox.local_jupyter.manager import (
    LOCAL_JUPYTER_KERNEL_NAME,
    LocalJupyterHandle,
)
from giga_agent.sandbox.local_jupyter.runtime import LocalJupyterSandbox
from giga_agent.sandbox.manager.types import SetSandboxStatusAction


class LocalJupyterSandboxTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    async def test_validate_settings_requires_jupyter_dependencies(self):
        with patch(
            "giga_agent.sandbox.local_jupyter.runtime.ensure_jupyter_dependencies",
            side_effect=MissingDependenciesError(["jupyter_server", "ipykernel"]),
        ):
            with self.assertRaises(MissingDependenciesError):
                await LocalJupyterSandbox.validate_settings({})

    async def test_up_uses_singleton_manager_handle(self):
        handle = LocalJupyterHandle(
            pid=12345,
            port=8888,
            token="secret-token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/jupyter-runtime",
            working_dir="/tmp/jupyter-workdir",
            started_at=1.0,
        )
        manager = types.SimpleNamespace(ensure_started=AsyncMock(return_value=handle))

        with patch(
            "giga_agent.sandbox.local_jupyter.runtime.get_local_jupyter_server_manager",
            return_value=manager,
        ), patch(
            "giga_agent.sandbox.local_jupyter.runtime.ensure_jupyter_dependencies",
            return_value=None,
        ):
            runtime = LocalJupyterSandbox(owner_id=uuid.uuid4())
            await runtime.up()

        self.assertEqual(runtime.base_url, handle.base_url)
        self.assertEqual(runtime.jupyter_token, handle.token)
        self.assertEqual(runtime.external_id, str(handle.pid))

    async def test_local_jupyter_requests_dedicated_kernel(self):
        runtime = LocalJupyterSandbox(owner_id=uuid.uuid4())
        self.assertEqual(
            runtime._get_kernel_request_payload(),
            {"name": LOCAL_JUPYTER_KERNEL_NAME},
        )

    async def test_upload_read_delete_bucket_file(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH": tmp_dir},
            clear=False,
        ):
            runtime = LocalJupyterSandbox(owner_id=owner_id)

            with patch.object(runtime, "_random_key_suffix", return_value="ABCDEFGH"):
                sandbox_path = await runtime.upload_file(
                    owner_id=owner_id,
                    file_name="notes/report.txt",
                    content=b"hello",
                )

            self.assertEqual(
                sandbox_path,
                os.path.realpath(
                    os.path.join(
                        tmp_dir,
                        str(owner_id),
                        "notes",
                        "report--ABCDEFGH.txt",
                    )
                ),
            )
            result = await runtime.read_file(sandbox_path)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"hello")

            await runtime.delete_file(sandbox_path)
            with self.assertRaises(FileNotFoundError):
                await runtime.read_file(sandbox_path)

    async def test_read_file_can_access_any_absolute_system_path(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir:
            outside_path = os.path.join(tmp_dir, "outside.txt")
            with open(outside_path, "wb") as file_obj:
                file_obj.write(b"system-data")

            runtime = LocalJupyterSandbox(owner_id=owner_id)
            result = await runtime.read_file(outside_path)

        self.assertIsInstance(result, ContentResult)
        self.assertEqual(result.data, b"system-data")

    async def test_cleanup_orphans_marks_running_sandboxes_stopped_when_server_missing(self):
        sandbox = types.SimpleNamespace(
            id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            status=SandboxStatus.RUNNING,
        )
        manager = types.SimpleNamespace(get_active_handle=AsyncMock(return_value=None))

        with patch(
            "giga_agent.sandbox.local_jupyter.runtime.get_local_jupyter_server_manager",
            return_value=manager,
        ):
            actions = await LocalJupyterSandbox.cleanup_orphans(
                providers=[],
                sandboxes=[sandbox],
            )

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], SetSandboxStatusAction)
