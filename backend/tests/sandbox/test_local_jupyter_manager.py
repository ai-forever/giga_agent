import asyncio
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.sandbox.local_jupyter.manager import (
    LOCAL_JUPYTER_KERNEL_NAME,
    LocalJupyterHandle,
    LocalJupyterServerManager,
)


class LocalJupyterServerManagerTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    async def test_ensure_started_serializes_concurrent_calls(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=12345,
            port=8888,
            token="token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )
        manager._get_active_handle = AsyncMock(side_effect=[None, handle])  # type: ignore[method-assign]
        manager._start_new_server = AsyncMock(return_value=handle)  # type: ignore[method-assign]

        first, second = await asyncio.gather(
            manager.ensure_started(),
            manager.ensure_started(),
        )

        self.assertEqual(first, handle)
        self.assertEqual(second, handle)
        manager._start_new_server.assert_awaited_once()

    async def test_stop_uses_force_kill_when_process_does_not_exit_gracefully(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=43210,
            port=9999,
            token="token",
            base_url="http://127.0.0.1:9999",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )

        manager._get_active_handle = AsyncMock(return_value=handle)  # type: ignore[method-assign]
        manager._wait_for_exit = AsyncMock(side_effect=[False, True])  # type: ignore[method-assign]
        manager._terminate_process_group = Mock()  # type: ignore[method-assign]
        manager._clear_state_unlocked = AsyncMock()  # type: ignore[method-assign]

        await manager.stop()

        self.assertEqual(
            manager._terminate_process_group.call_args_list,
            [
                unittest.mock.call(handle.pid, force=False),
                unittest.mock.call(handle.pid, force=True),
            ],
        )
        manager._clear_state_unlocked.assert_awaited_once()

    async def test_cleanup_stale_state_removes_dead_metadata(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=11111,
            port=7777,
            token="token",
            base_url="http://127.0.0.1:7777",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )
        manager._read_metadata_file = Mock(return_value=handle)  # type: ignore[method-assign]
        manager._is_pid_alive = Mock(return_value=False)  # type: ignore[method-assign]
        manager._clear_state_unlocked = AsyncMock()  # type: ignore[method-assign]

        await manager.cleanup_stale_state()

        manager._clear_state_unlocked.assert_awaited_once()

    async def test_write_and_read_metadata_roundtrip(self):
        manager = LocalJupyterServerManager()
        handle = LocalJupyterHandle(
            pid=24680,
            port=8888,
            token="token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )

        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_PROJECT_ROOT": tmp_dir},
            clear=False,
        ):
            manager._write_metadata_file(handle)
            loaded = manager._read_metadata_file()

        self.assertEqual(loaded, handle)

    async def test_start_new_server_uses_isolated_jupyter_env(self):
        manager = LocalJupyterServerManager()
        proc = Mock(pid=24680)
        supervisor = Mock()
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            working_dir = project_root / "local_jupyter" / "workspace"
            config_dir = project_root / "local_jupyter" / "config"
            data_dir = project_root / "local_jupyter" / "data"
            runtime_dir = project_root / "local_jupyter" / "runtime"
            shims_dir = project_root / "local_jupyter" / "shims"
        manager._reserve_port = Mock(return_value=8888)  # type: ignore[method-assign]
        manager._working_dir = Mock(return_value=working_dir)  # type: ignore[method-assign]
        manager._config_dir = Mock(return_value=config_dir)  # type: ignore[method-assign]
        manager._data_dir = Mock(return_value=data_dir)  # type: ignore[method-assign]
        manager._runtime_dir = Mock(return_value=runtime_dir)  # type: ignore[method-assign]
        manager._shims_dir = Mock(return_value=shims_dir)  # type: ignore[method-assign]
        manager._wait_until_ready = AsyncMock(return_value=None)  # type: ignore[method-assign]

        with patch(
            "giga_agent.sandbox.local_jupyter.manager.ensure_jupyter_dependencies",
            return_value=None,
        ), patch(
            "giga_agent.sandbox.local_jupyter.manager.subprocess.Popen",
            return_value=proc,
        ) as popen_mock, patch(
            "giga_agent.sandbox.local_jupyter.manager.get_process_supervisor",
            return_value=supervisor,
        ):
            handle = await manager._start_new_server()

        self.assertEqual(handle.pid, proc.pid)
        popen_mock.assert_called_once()

        command = popen_mock.call_args.args[0]
        env = popen_mock.call_args.kwargs["env"]
        kernel_spec_path = data_dir / "kernels" / LOCAL_JUPYTER_KERNEL_NAME / "kernel.json"
        kernel_spec = json.loads(kernel_spec_path.read_text(encoding="utf-8"))

        self.assertIn("--IdentityProvider.token=", " ".join(command))
        self.assertNotIn("--ServerApp.token=", " ".join(command))
        self.assertNotIn("--ServerApp.runtime_dir=", " ".join(command))
        self.assertEqual(env["JUPYTER_NO_CONFIG"], "1")
        self.assertEqual(env["JUPYTER_CONFIG_DIR"], str(config_dir))
        self.assertEqual(env["JUPYTER_DATA_DIR"], str(data_dir))
        self.assertEqual(env["JUPYTER_RUNTIME_DIR"], str(runtime_dir))
        self.assertTrue((shims_dir / "pip").is_file())
        self.assertTrue((shims_dir / "python").is_file())
        self.assertEqual(
            kernel_spec["argv"][0],
            manager._python_executable(),
        )
        self.assertEqual(kernel_spec["env"]["PIP_REQUIRE_VIRTUALENV"], "1")
        self.assertTrue(
            kernel_spec["env"]["PATH"].startswith(
                f"{shims_dir}{os.pathsep}"
            )
        )
        supervisor.register_process.assert_called_once()

    async def test_clear_state_unregisters_supervised_process(self):
        manager = LocalJupyterServerManager()
        manager._handle = LocalJupyterHandle(
            pid=13579,
            port=8888,
            token="token",
            base_url="http://127.0.0.1:8888",
            runtime_dir="/tmp/runtime",
            working_dir="/tmp/workdir",
            started_at=1.0,
        )
        supervisor = Mock()

        with patch(
            "giga_agent.sandbox.local_jupyter.manager.get_process_supervisor",
            return_value=supervisor,
        ):
            await manager._clear_state_unlocked()

        supervisor.unregister_process.assert_called_once_with(
            kind="local_jupyter",
            pid=13579,
        )

    async def test_enforce_kernel_limit_evicts_lru_kernel(self):
        manager = LocalJupyterServerManager()
        manager.note_kernel_use("user-a", "k1")
        manager.note_kernel_use("user-a", "k2")
        # Reusing k1 makes it most-recently-used, so k2 is now the LRU.
        manager.note_kernel_use("user-a", "k1")
        deleted: list[str] = []
        manager._delete_kernel = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *_a, **_k: deleted.append(_a[2])
        )

        await manager.enforce_kernel_limit(
            owner_id="user-a",
            limit=2,
            base_url="http://127.0.0.1:8888",
            token="token",
        )

        self.assertEqual(deleted, ["k2"])
        self.assertEqual(list(manager._owner_kernels["user-a"].keys()), ["k1"])

    async def test_enforce_kernel_limit_is_scoped_per_owner(self):
        manager = LocalJupyterServerManager()
        manager.note_kernel_use("user-a", "k1")
        manager.note_kernel_use("user-b", "k2")
        manager._delete_kernel = AsyncMock()  # type: ignore[method-assign]

        await manager.enforce_kernel_limit(
            owner_id="user-a",
            limit=2,
            base_url="http://127.0.0.1:8888",
            token="token",
        )

        manager._delete_kernel.assert_not_awaited()

    async def test_enforce_kernel_limit_noop_when_disabled(self):
        manager = LocalJupyterServerManager()
        manager.note_kernel_use("user-a", "k1")
        manager.note_kernel_use("user-a", "k2")
        manager._delete_kernel = AsyncMock()  # type: ignore[method-assign]

        await manager.enforce_kernel_limit(
            owner_id="user-a",
            limit=0,
            base_url="http://127.0.0.1:8888",
            token="token",
        )

        manager._delete_kernel.assert_not_awaited()
