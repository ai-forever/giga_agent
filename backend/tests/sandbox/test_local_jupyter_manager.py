import asyncio
import json
import os
import subprocess
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
    get_local_jupyter_server_manager,
)
from giga_agent.utils.sandbox_exec_mac import MacSandboxExecLaunch


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

    def test_get_manager_uses_env_safe_flag_when_param_is_not_provided(self):
        with self._patched_env({"GIGA_AGENT_LOCAL_JUPYTER_SAFE": "true"}), patch(
            "giga_agent.sandbox.local_jupyter.manager._MANAGER",
            None,
        ):
            manager = get_local_jupyter_server_manager()

        self.assertTrue(manager._safe)

    def test_get_manager_prefers_explicit_safe_param_over_env(self):
        with self._patched_env({"GIGA_AGENT_LOCAL_JUPYTER_SAFE": "true"}), patch(
            "giga_agent.sandbox.local_jupyter.manager._MANAGER",
            None,
        ):
            manager = get_local_jupyter_server_manager(safe=False)

        self.assertFalse(manager._safe)

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
            ipython_dir = config_dir / "ipython"
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
        self.assertEqual(env["IPYTHONDIR"], str(ipython_dir.resolve()))
        self.assertTrue((shims_dir / "pip").is_file())
        self.assertTrue((shims_dir / "python").is_file())
        startup_file = ipython_dir / "profile_default" / "startup" / "00-giga-agent-shell.py"
        self.assertTrue(startup_file.is_file())
        self.assertIn(
            "_giga_agent_system_no_pty",
            startup_file.read_text(encoding="utf-8"),
        )
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

    def test_launch_server_uses_macos_sandbox_when_safe_enabled(self):
        manager = LocalJupyterServerManager(safe=True)
        proc = Mock(pid=1234)
        runtime_dir = Path("/tmp/runtime")
        config_dir = Path("/tmp/config")
        data_dir = Path("/tmp/data")
        shims_dir = Path("/tmp/shims")
        log_path = Path("/tmp/server.log")
        working_dir = Path("/tmp/workspace")

        with tempfile.TemporaryFile("wb") as log_handle:
            manager._log_handle = log_handle
            with patch(
                "giga_agent.sandbox.local_jupyter.manager.platform.system",
                return_value="Darwin",
            ), patch(
                "giga_agent.sandbox.local_jupyter.manager.launch_with_macos_sandbox",
                return_value=MacSandboxExecLaunch(
                    process=proc,
                    profile_path=log_path.with_suffix(".sandbox.sb"),
                    profile="profile",
                    command=["/usr/bin/sandbox-exec"],
                ),
            ) as launch_mock:
                launched = manager._launch_server(
                    command=["python", "-m", "jupyter", "server"],
                    env={"ENV": "1"},
                    runtime_dir=runtime_dir,
                    config_dir=config_dir,
                    data_dir=data_dir,
                    shims_dir=shims_dir,
                ipython_dir=config_dir / "ipython",
                    log_path=log_path,
                    working_dir=working_dir,
                    port=8888,
                )

        self.assertIs(launched, proc)
        launch_config = launch_mock.call_args.args[0]
        self.assertEqual(launch_config.command, ["python", "-m", "jupyter", "server"])
        self.assertEqual(launch_config.cwd, working_dir.resolve())
        self.assertEqual(launch_config.read_roots, [Path("/")])
        self.assertEqual(launch_config.deny_read_roots, [Path.home() / ".ssh"])
        self.assertEqual(
            launch_config.write_roots,
            [
                runtime_dir.resolve(),
                config_dir.resolve(),
                data_dir.resolve(),
                shims_dir.resolve(),
                (config_dir / "ipython").resolve(),
                log_path.parent.resolve(),
            ],
        )
        self.assertEqual(launch_config.local_network_port, 8888)
        self.assertTrue(launch_config.allow_local_network_all_ports)
        self.assertFalse(launch_config.allow_outbound_network)
        self.assertIs(launch_config.stdout, manager._log_handle)
        self.assertEqual(launch_config.stderr, subprocess.STDOUT)

    def test_launch_server_safe_mode_requires_macos(self):
        manager = LocalJupyterServerManager(safe=True)
        with tempfile.TemporaryFile("wb") as log_handle:
            manager._log_handle = log_handle
            with patch(
                "giga_agent.sandbox.local_jupyter.manager.platform.system",
                return_value="Linux",
            ):
                with self.assertRaisesRegex(RuntimeError, "only supported on macOS"):
                    manager._launch_server(
                        command=["python", "-m", "jupyter", "server"],
                        env={"ENV": "1"},
                        runtime_dir=Path("/tmp/runtime"),
                        config_dir=Path("/tmp/config"),
                        data_dir=Path("/tmp/data"),
                        shims_dir=Path("/tmp/shims"),
                    ipython_dir=Path("/tmp/config/ipython"),
                        log_path=Path("/tmp/server.log"),
                        working_dir=Path("/tmp/workspace"),
                        port=8888,
                    )
