import os
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.jupyter import _inject_env_prelude
from giga_agent.sandbox.local_jupyter.dependencies import MissingDependenciesError
from giga_agent.sandbox.local_jupyter.manager import (
    LOCAL_JUPYTER_KERNEL_NAME,
    LocalJupyterHandle,
)
from giga_agent.sandbox.local_jupyter.runtime import LocalJupyterSandbox
from giga_agent.sandbox.local_jupyter.shell import LocalJupyterShellMeta
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

    async def test_legacy_settings_fields_are_ignored(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env(
                {"GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH": tmp_dir},
                clear=False,
            ),
            patch(
                "giga_agent.sandbox.local_jupyter.runtime.ensure_jupyter_dependencies",
                return_value=None,
            ),
        ):
            validated = await LocalJupyterSandbox.validate_settings(
                {
                    "startup_timeout_sec": 45,
                    "graceful_shutdown_timeout_sec": 10,
                    "working_dir": "/tmp/workdir",
                    "files_path": "/tmp/legacy-files",
                    "python_executable": "/tmp/python",
                }
            )
            runtime = LocalJupyterSandbox(
                owner_id=uuid.uuid4(),
                startup_timeout_sec=45,
                graceful_shutdown_timeout_sec=10,
                working_dir="/tmp/workdir",
                files_path="/tmp/legacy-files",
                python_executable="/tmp/python",
            )

        self.assertEqual(validated, {})
        self.assertEqual(runtime._sandbox_root_dir, Path(tmp_dir).resolve())

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

        with (
            patch(
                "giga_agent.sandbox.local_jupyter.runtime.get_local_jupyter_server_manager",
                return_value=manager,
            ),
            patch(
                "giga_agent.sandbox.local_jupyter.runtime.ensure_jupyter_dependencies",
                return_value=None,
            ),
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

    async def test_inject_env_prelude_updates_existing_envs(self):
        namespace: dict[str, object] = {}
        first_code = _inject_env_prelude(
            "import os\nsnapshot = dict(os.environ)",
            {"api_key": "first", "EMPTY": ""},
        )
        second_code = _inject_env_prelude(
            "import os\nsnapshot = dict(os.environ)",
            {"NEXT_TOKEN": "second"},
        )

        with patch.dict(os.environ, {}, clear=True):
            exec(first_code, namespace)
            first_snapshot = dict(namespace["snapshot"])

            exec(second_code, namespace)
            second_snapshot = dict(namespace["snapshot"])

        self.assertEqual(first_snapshot["api_key"], "first")
        self.assertEqual(first_snapshot["EMPTY"], "")
        self.assertEqual(second_snapshot["api_key"], "first")
        self.assertEqual(second_snapshot["EMPTY"], "")
        self.assertEqual(second_snapshot["NEXT_TOKEN"], "second")
        self.assertNotIn("_giga_agent_envs", namespace)
        self.assertNotIn("_giga_agent_json", namespace)
        self.assertNotIn("_giga_agent_os", namespace)

    async def test_upload_read_delete_bucket_file(self):
        owner_id = uuid.uuid4()
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env(
                {"GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH": tmp_dir},
                clear=False,
            ),
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

    async def test_cleanup_orphans_marks_running_sandboxes_stopped_when_server_missing(
        self,
    ):
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


class LocalJupyterShellTests(unittest.IsolatedAsyncioTestCase):
    """Tests for run_shell / await_shell on LocalJupyterSandbox."""

    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    def _make_runtime(self, tmp_dir: str) -> LocalJupyterSandbox:
        return LocalJupyterSandbox(owner_id=uuid.uuid4())

    def _mock_manager(self, working_dir: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            _working_dir=Mock(return_value=Path(working_dir)),
            get_shell_env=Mock(return_value=os.environ.copy()),
        )

    async def test_run_shell_echo_completes(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=Mock(
                        register_process=Mock(),
                        unregister_process=Mock(),
                        list_processes=Mock(return_value=[]),
                    ),
                ),
            ):
                result = await runtime.run_shell("echo hello-world")

            self.assertEqual(result.status, "completed")
            self.assertFalse(result.backgrounded)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("hello-world", result.output)
            self.assertIsNone(result.await_hint)

    async def test_run_shell_backgrounds_with_zero_block(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=Mock(
                        register_process=Mock(),
                        unregister_process=Mock(),
                        list_processes=Mock(return_value=[]),
                    ),
                ),
            ):
                result = await runtime.run_shell(
                    "sleep 10",
                    block_until_ms=0,
                    description="Long sleep",
                )

            self.assertTrue(result.backgrounded)
            self.assertEqual(result.status, "running")
            self.assertIn("await_shell", result.await_hint or "")

            popen = runtime._get_processes().get(result.shell_id)
            if popen is not None:
                popen.kill()
                popen.wait()

    async def test_await_shell_reads_new_output(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                result = await runtime.run_shell(
                    "echo part1 && sleep 0.1 && echo part2",
                    block_until_ms=0,
                    description="Two parts",
                )
                self.assertTrue(result.backgrounded)

                await_result = await runtime.await_shell(
                    result.shell_id,
                    block_until_ms=5000,
                )

            self.assertEqual(await_result.status, "completed")
            self.assertEqual(await_result.exit_code, 0)
            combined = result.output + await_result.output_delta
            self.assertIn("part1", combined)
            self.assertIn("part2", combined)

    async def test_await_shell_with_pattern(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                result = await runtime.run_shell(
                    "echo MARKER-START && sleep 0.2 && echo MARKER-END",
                    block_until_ms=0,
                )
                await_result = await runtime.await_shell(
                    result.shell_id,
                    block_until_ms=5000,
                    pattern="MARKER-END",
                )

            self.assertTrue(await_result.matched_pattern)

            popen = runtime._get_processes().get(result.shell_id)
            if popen is not None:
                popen.kill()
                popen.wait()

    async def test_await_shell_not_found(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            runtime = self._make_runtime(tmp_dir)
            result = await runtime.await_shell("nonexistent-id-12345")

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.output_delta, "")

    async def test_run_shell_uses_manager_working_dir(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            work_dir = os.path.join(tmp_dir, "custom_workspace")
            os.makedirs(work_dir)
            manager = self._mock_manager(work_dir)
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                result = await runtime.run_shell("pwd")

            self.assertEqual(result.cwd, work_dir)

    async def test_run_shell_env_contains_shims_path(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            shims_dir = os.path.join(tmp_dir, "shims")
            os.makedirs(shims_dir)
            env_with_shims = os.environ.copy()
            env_with_shims["PATH"] = (
                shims_dir + os.pathsep + env_with_shims.get("PATH", "")
            )

            manager = types.SimpleNamespace(
                _working_dir=Mock(return_value=Path(tmp_dir)),
                get_shell_env=Mock(return_value=env_with_shims),
            )
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                result = await runtime.run_shell("echo $PATH", block_until_ms=5000)

            self.assertIn(shims_dir, result.output)

    async def test_run_shell_empty_command_raises(self):
        runtime = LocalJupyterSandbox(owner_id=uuid.uuid4())
        with self.assertRaises(ValueError):
            await runtime.run_shell("")

    async def test_run_shell_negative_block_until_raises(self):
        runtime = LocalJupyterSandbox(owner_id=uuid.uuid4())
        with self.assertRaises(ValueError):
            await runtime.run_shell("echo ok", block_until_ms=-1)

    async def test_await_shell_invalid_pattern_raises(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            runtime = self._make_runtime(tmp_dir)
            with self.assertRaises(ValueError):
                await runtime.await_shell("some-id", pattern="[invalid")

    async def test_run_shell_failed_exit_code(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                result = await runtime.run_shell("exit 42")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.exit_code, 42)

    async def test_shell_sessions_stored_in_correct_dir(self):
        runtime = LocalJupyterSandbox(owner_id=uuid.uuid4())
        root = runtime._shell_sessions_root()
        self.assertTrue(
            str(root).endswith(os.path.join("local_jupyter", "shell_sessions")),
        )

    async def test_reconcile_with_popen_lost_and_exit_code_file(self):
        """After hot-reload: Popen lost but exit_code file exists."""
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            runtime = self._make_runtime(tmp_dir)
            shell_id = "test-reconcile-123"
            session_dir = runtime._shell_session_dir(shell_id)
            session_dir.mkdir(parents=True, exist_ok=True)

            exit_code_path = runtime._shell_exit_code_path(shell_id)
            exit_code_path.write_text("0\n", encoding="utf-8")

            meta = LocalJupyterShellMeta(
                shell_id=shell_id,
                command="echo done",
                cwd=tmp_dir,
                status="running",
                started_at="2026-04-14T12:00:00Z",
                pid=99999,
                output_path=str(runtime._shell_log_path(shell_id)),
                exit_code_path=str(exit_code_path),
                last_update_at="2026-04-14T12:00:00Z",
            )

            runtime._shell_log_path(shell_id).write_bytes(b"output data\n")

            with patch(
                "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                return_value=Mock(
                    unregister_process=Mock(),
                    list_processes=Mock(return_value=[]),
                ),
            ):
                result = runtime._reconcile_shell_meta(meta)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.exit_code, 0)

    async def test_reconcile_popen_lost_no_exit_code_not_supervised_marks_failed(self):
        """After hot-reload: Popen lost, no exit_code, not in supervisor -> failed."""
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            runtime = self._make_runtime(tmp_dir)
            shell_id = "test-orphan-456"
            session_dir = runtime._shell_session_dir(shell_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            runtime._shell_log_path(shell_id).write_bytes(b"")

            meta = LocalJupyterShellMeta(
                shell_id=shell_id,
                command="sleep 1000",
                cwd=tmp_dir,
                status="running",
                started_at="2026-04-14T12:00:00Z",
                pid=99998,
                output_path=str(runtime._shell_log_path(shell_id)),
                exit_code_path=str(runtime._shell_exit_code_path(shell_id)),
                last_update_at="2026-04-14T12:00:00Z",
            )

            with patch(
                "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                return_value=Mock(
                    unregister_process=Mock(),
                    list_processes=Mock(return_value=[]),
                ),
            ):
                result = runtime._reconcile_shell_meta(meta)

            self.assertEqual(result.status, "failed")

    async def test_supervisor_register_called_on_run_shell(self):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            self._patched_env({"GIGA_AGENT_PROJECT_ROOT": tmp_dir}, clear=False),
        ):
            manager = self._mock_manager(tmp_dir)
            runtime = self._make_runtime(tmp_dir)
            supervisor = Mock(
                register_process=Mock(),
                unregister_process=Mock(),
                list_processes=Mock(return_value=[]),
            )

            with (
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_local_jupyter_server_manager",
                    return_value=manager,
                ),
                patch(
                    "giga_agent.sandbox.local_jupyter.shell.get_process_supervisor",
                    return_value=supervisor,
                ),
            ):
                await runtime.run_shell("echo supervised")

            supervisor.register_process.assert_called_once()
            record = supervisor.register_process.call_args[0][0]
            self.assertEqual(record.kind, "local_jupyter_shell")
            self.assertIn("shell_id", record.metadata)
