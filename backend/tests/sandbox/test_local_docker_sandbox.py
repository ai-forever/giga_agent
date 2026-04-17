import asyncio
import os
import tempfile
import types
import unittest
import uuid
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.local_docker import LocalDockerSandbox, LocalDockerShellMeta
from giga_agent.sandbox.manager.types import (
    RemoveExternalRuntimeAction,
    SetSandboxStatusAction,
    StopExternalRuntimeAction,
)


class LocalDockerSandboxTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    async def test_validate_settings_requires_max_active(self):
        with self._patched_env({}, clear=False):
            os.environ.pop("GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES", None)
            with patch(
                "giga_agent.sandbox.local_docker.docker.from_env",
                return_value=types.SimpleNamespace(
                    ping=lambda: None, close=lambda: None
                ),
            ):
                with self.assertRaisesRegex(ValueError, "max_active_sandboxes"):
                    await LocalDockerSandbox.validate_settings(
                        {"max_active_sandboxes": None}
                    )

    async def test_validate_settings_uses_env_fallback_for_max_active(self):
        with self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES": "3"},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(ping=lambda: None, close=lambda: None),
        ):
            validated = await LocalDockerSandbox.validate_settings({})
        self.assertEqual(validated["max_active_sandboxes"], 3)

    async def test_validate_settings_uses_env_fallback_for_image(self):
        with self._patched_env(
            {
                "GIGA_AGENT_LOCAL_DOCKER_IMAGE": "registry.example/custom-sandbox:1.2.3",
                "GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES": "3",
            },
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(ping=lambda: None, close=lambda: None),
        ):
            validated = await LocalDockerSandbox.validate_settings({})
        self.assertEqual(validated["image"], "registry.example/custom-sandbox:1.2.3")

    async def test_validate_settings_fails_when_docker_unreachable(self):
        with self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES": "3"},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            side_effect=RuntimeError("daemon unavailable"),
        ):
            with self.assertRaisesRegex(ValueError, "Docker connection check failed"):
                await LocalDockerSandbox.validate_settings({})

    async def test_requires_running_for_read_delete(self):
        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        self.assertFalse(runtime.requires_running_for_read("/bucket/test.txt"))
        self.assertFalse(runtime.requires_running_for_delete("/bucket/test.txt"))
        self.assertTrue(runtime.requires_running_for_read("/tmp/test.txt"))
        self.assertTrue(runtime.requires_running_for_delete("/tmp/test.txt"))

    async def test_upload_read_delete_bucket_file(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_FILES_PATH": tmp_dir},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(owner_id=owner_id, max_active_sandboxes=1)

            with patch.object(runtime, "_random_key_suffix", return_value="ABCDEFGH"):
                sandbox_path = await runtime.upload_file(
                    owner_id=owner_id,
                    file_name="notes/report.txt",
                    content=b"hello",
                )
            self.assertEqual(sandbox_path, "/bucket/notes/report--ABCDEFGH.txt")

            result = await runtime.read_file(sandbox_path)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"hello")

            await runtime.delete_file(sandbox_path)
            with self.assertRaises(FileNotFoundError):
                await runtime.read_file(sandbox_path)

    async def test_bucket_path_rejects_traversal(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_FILES_PATH": tmp_dir},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(owner_id=owner_id, max_active_sandboxes=1)

            with self.assertRaises(ValueError):
                runtime._local_path_from_bucket_path("/bucket/../escape.txt")

    async def test_uniquify_bucket_rel_path_adds_suffix_before_plotly_json_extension(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_FILES_PATH": tmp_dir},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(owner_id=owner_id, max_active_sandboxes=1)
            with patch.object(runtime, "_random_key_suffix", return_value="ABCDEFGH"):
                rel = runtime._uniquify_bucket_rel_path(
                    owner_id=owner_id,
                    file_name="thread-1/chart.plotly.json",
                )

        self.assertEqual(rel.as_posix(), "thread-1/chart--ABCDEFGH.plotly.json")

    async def test_uniquify_bucket_rel_path_keeps_subdirectories(self):
        owner_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as tmp_dir, self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_FILES_PATH": tmp_dir},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(owner_id=owner_id, max_active_sandboxes=1)
            with patch.object(runtime, "_random_key_suffix", return_value="ABCDEFGH"):
                rel = runtime._uniquify_bucket_rel_path(
                    owner_id=owner_id,
                    file_name="thread-42/reports/report.txt",
                )

        self.assertEqual(rel.as_posix(), "thread-42/reports/report--ABCDEFGH.txt")

    async def test_up_passes_management_labels_to_container(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        container = types.SimpleNamespace(
            id="container-1",
            attrs={"NetworkSettings": {"Ports": {"8888/tcp": [{"HostPort": "12345"}]}}},
            reload=lambda: None,
            exec_run=lambda *args, **kwargs: None,
        )
        run_mock = Mock(return_value=container)
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(run=run_mock)
        )

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=client,
        ), patch.object(
            LocalDockerSandbox,
            "is_up",
            return_value=True,
        ):
            runtime = LocalDockerSandbox(
                owner_id=owner_id,
                provider_id=provider_id,
                sandbox_id=sandbox_id,
                max_active_sandboxes=1,
            )
            await runtime.up()

        labels = run_mock.call_args.kwargs["labels"]
        self.assertEqual(labels["giga_agent.managed"], "true")
        self.assertEqual(labels["giga_agent.provider_id"], str(provider_id))
        self.assertEqual(labels["giga_agent.sandbox_id"], str(sandbox_id))
        self.assertEqual(labels["giga_agent.owner_id"], str(owner_id))

    async def test_up_does_not_start_jupyter_eagerly(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        exec_run = Mock()
        container = types.SimpleNamespace(
            id="container-1",
            attrs={"NetworkSettings": {"Ports": {"8888/tcp": [{"HostPort": "12345"}]}}},
            reload=Mock(),
            exec_run=exec_run,
        )
        client = types.SimpleNamespace(containers=types.SimpleNamespace(run=Mock(return_value=container)))

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=client,
        ):
            runtime = LocalDockerSandbox(
                owner_id=owner_id,
                provider_id=provider_id,
                sandbox_id=sandbox_id,
                max_active_sandboxes=1,
            )
            await runtime.up()

        self.assertEqual(runtime.base_url, "http://localhost:12345")
        exec_run.assert_not_called()

    async def test_is_up_uses_container_liveness(self):
        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        runtime._container = types.SimpleNamespace(
            reload=Mock(),
            attrs={"State": {"Running": True}, "NetworkSettings": {"Ports": {}}},
        )
        runtime._ensure_container_connected = AsyncMock(return_value=None)
        self.assertTrue(await runtime.is_up())

        runtime._container = types.SimpleNamespace(
            reload=Mock(),
            attrs={"State": {"Running": False}, "NetworkSettings": {"Ports": {}}},
        )
        self.assertFalse(await runtime.is_up())

    async def test_run_code_starts_jupyter_lazily_and_resets_kernel_after_restart(self):
        observed: dict[str, object] = {}

        async def fake_super_run_code(
            _self,
            code: str,
            kernel_id: str | None = None,
            *,
            allow_stdin: bool = True,
            envs: dict[str, str] | None = None,
            **kwargs,
        ):
            observed["code"] = code
            observed["kernel_id"] = kernel_id
            observed["allow_stdin"] = allow_stdin
            observed["envs"] = envs
            observed["kwargs"] = kwargs
            yield {"type": "stdout", "text": "ok"}

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        runtime._kernel_id = "persisted-kernel"

        with patch.object(
            runtime,
            "_ensure_jupyter_ready",
            AsyncMock(return_value=True),
        ) as ensure_ready, patch.object(
            JupyterSandbox,
            "run_code",
            new=fake_super_run_code,
        ):
            chunks = [
                chunk
                async for chunk in runtime.run_code(
                    "print('hi')",
                    kernel_id="persisted-kernel",
                    envs={"A": "1"},
                )
            ]

        ensure_ready.assert_awaited_once()
        self.assertEqual(chunks, [{"type": "stdout", "text": "ok"}])
        self.assertIsNone(observed["kernel_id"])
        self.assertEqual(observed["envs"], {"A": "1"})
        self.assertIsNone(runtime._kernel_id)

    async def test_ensure_jupyter_ready_serializes_start_with_cache_lock(self):
        sandbox_id = uuid.uuid4()
        ready_state = {"ready": False}
        lock_map: dict[str, asyncio.Lock] = {}

        @asynccontextmanager
        async def fake_lock_cm(key: str, **_kwargs):
            lock = lock_map.setdefault(key, asyncio.Lock())
            await lock.acquire()
            try:
                yield
            finally:
                lock.release()

        async def fake_is_ready() -> bool:
            return ready_state["ready"]

        async def fake_start() -> None:
            await asyncio.sleep(0)
            ready_state["ready"] = True

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(
                sandbox_id=sandbox_id,
                max_active_sandboxes=1,
            )

        with patch(
            "giga_agent.sandbox.local_docker.cache.lock",
            side_effect=fake_lock_cm,
        ), patch.object(
            runtime,
            "_is_jupyter_ready",
            AsyncMock(side_effect=fake_is_ready),
        ), patch.object(
            runtime,
            "_is_container_up",
            AsyncMock(return_value=True),
        ), patch.object(
            runtime,
            "_start_jupyter_server",
            AsyncMock(side_effect=fake_start),
        ) as start_jupyter:
            results = await asyncio.gather(
                runtime._ensure_jupyter_ready(),
                runtime._ensure_jupyter_ready(),
            )

        self.assertEqual(start_jupyter.await_count, 1)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    async def test_cleanup_orphans_returns_remove_for_unbound_container(self):
        sandbox_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        container = types.SimpleNamespace(
            id="container-1",
            labels={
                "giga_agent.managed": "true",
                "giga_agent.provider_type": "local_docker",
                "giga_agent.provider_id": str(provider_id),
                "giga_agent.sandbox_id": str(sandbox_id),
                "giga_agent.owner_id": str(uuid.uuid4()),
            },
            attrs={"Config": {"Labels": {}}, "State": {"Running": True}},
            reload=lambda: None,
        )
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(
                list=lambda *args, **kwargs: [container],
            ),
            close=lambda: None,
        )

        with patch.object(LocalDockerSandbox, "_make_docker_client", return_value=client):
            actions = await LocalDockerSandbox.cleanup_orphans(
                providers=[],
                sandboxes=[],
            )

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], RemoveExternalRuntimeAction)

    async def test_cleanup_orphans_returns_stop_and_status_for_live_stopped_sandbox(self):
        sandbox_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        container = types.SimpleNamespace(
            id="container-1",
            labels={
                "giga_agent.managed": "true",
                "giga_agent.provider_type": "local_docker",
                "giga_agent.provider_id": str(provider_id),
                "giga_agent.sandbox_id": str(sandbox_id),
                "giga_agent.owner_id": str(uuid.uuid4()),
            },
            attrs={"Config": {"Labels": {}}, "State": {"Running": True}},
            reload=lambda: None,
        )
        sandbox = types.SimpleNamespace(
            id=sandbox_id,
            provider_id=provider_id,
            owner_id=uuid.uuid4(),
            status=SandboxStatus.STOPPED,
            external_id="container-1",
            settings={},
        )
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(list=lambda *args, **kwargs: [container]),
            close=lambda: None,
        )

        with patch.object(LocalDockerSandbox, "_make_docker_client", return_value=client):
            actions = await LocalDockerSandbox.cleanup_orphans(
                providers=[],
                sandboxes=[sandbox],
            )

        self.assertEqual(len(actions), 2)
        self.assertIsInstance(actions[0], StopExternalRuntimeAction)
        self.assertIsInstance(actions[1], SetSandboxStatusAction)

    async def test_shell_paths_use_hidden_runtime_dir(self):
        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        self.assertEqual(
            str(runtime._shell_sessions_root()),
            "/root/.giga_agent/shell_sessions",
        )
        self.assertEqual(
            str(runtime._shell_meta_path("abc123")),
            "/root/.giga_agent/shell_sessions/abc123/meta.json",
        )
        self.assertEqual(
            str(runtime._shell_log_path("abc123")),
            "/root/.giga_agent/shell_sessions/abc123/output.log",
        )
        self.assertEqual(
            str(runtime._shell_exit_code_path("abc123")),
            "/root/.giga_agent/shell_sessions/abc123/exit_code",
        )

    async def test_run_shell_backgrounds_and_advances_offset(self):
        output_bytes = b"line-1\nline-2\n"
        written_meta: list[LocalDockerShellMeta] = []
        start_shell_exec = AsyncMock(return_value=777)
        secret_envs = {"API_KEY": "very-secret"}

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        with patch.object(
            runtime,
            "_initialize_shell_session",
            new=AsyncMock(return_value=None),
        ), patch.object(
            runtime,
            "_start_shell_exec",
            new=start_shell_exec,
        ), patch.object(
            runtime,
            "_reconcile_shell_meta",
            new=AsyncMock(side_effect=lambda meta: meta),
        ), patch.object(
            runtime,
            "_get_container_file_size",
            new=AsyncMock(return_value=len(output_bytes)),
        ), patch.object(
            runtime,
            "_read_container_file_range",
            new=AsyncMock(return_value=output_bytes),
        ), patch.object(
            runtime,
            "_write_shell_meta",
            new=AsyncMock(side_effect=lambda meta: written_meta.append(meta)),
        ):
            result = await runtime.run_shell(
                "echo hello",
                block_until_ms=0,
                description="Echo test",
                envs=secret_envs,
            )

        self.assertTrue(result.backgrounded)
        self.assertEqual(result.status, "running")
        self.assertEqual(result.output, output_bytes.decode())
        self.assertIn('await_shell(shell_id="', result.await_hint or "")
        start_shell_exec.assert_awaited_once_with(
            shell_id=result.shell_id,
            command="echo hello",
            cwd="/root",
            envs=secret_envs,
        )
        self.assertEqual(len(written_meta), 2)
        self.assertEqual(written_meta[0].pid, 777)
        self.assertEqual(written_meta[0].command, "echo hello")
        self.assertNotIn("very-secret", written_meta[0].model_dump_json())
        self.assertEqual(written_meta[1].last_delivered_offset, len(output_bytes))

    async def test_start_shell_exec_returns_background_pid(self):
        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        with patch.object(
            runtime,
            "_run_exec_in_container",
            new=AsyncMock(return_value=(0, b"4321\n")),
        ) as run_exec:
            pid = await runtime._start_shell_exec(
                shell_id="abc123",
                command="echo ok",
                cwd="/root",
                envs={"API_KEY": "secret"},
            )

        self.assertEqual(pid, 4321)
        cmd = run_exec.await_args.kwargs["cmd"]
        self.assertEqual(cmd[0], "python")
        self.assertEqual(cmd[1], "-c")
        self.assertEqual(cmd[3], "/root")
        self.assertEqual(cmd[4], "/root/.giga_agent/shell_sessions/abc123/output.log")
        self.assertIn(
            "/root/.giga_agent/shell_sessions/abc123/exit_code",
            cmd[5],
        )
        self.assertEqual(cmd[6], '{"API_KEY": "secret"}')

    async def test_await_shell_reconciles_completion_and_reads_only_new_output(self):
        initial_meta = LocalDockerShellMeta(
            shell_id="abc123",
            command="sleep 1",
            cwd="/root",
            status="running",
            started_at="2026-04-14T12:00:00Z",
            pid=777,
            output_path="/root/.giga_agent/shell_sessions/abc123/output.log",
            exit_code_path="/root/.giga_agent/shell_sessions/abc123/exit_code",
            output_size_bytes=4,
            last_delivered_offset=4,
            last_update_at="2026-04-14T12:00:00Z",
        )
        written_meta: list[LocalDockerShellMeta] = []

        with patch(
            "giga_agent.sandbox.local_docker.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(max_active_sandboxes=1)

        with patch.object(
            runtime,
            "_read_shell_meta",
            new=AsyncMock(return_value=initial_meta),
        ), patch.object(
            runtime,
            "_read_shell_exit_code",
            new=AsyncMock(return_value=0),
        ), patch.object(
            runtime,
            "_get_container_file_size",
            new=AsyncMock(side_effect=[7, 7]),
        ), patch.object(
            runtime,
            "_read_container_file_range",
            new=AsyncMock(return_value=b"xyz"),
        ), patch.object(
            runtime,
            "_write_shell_meta",
            new=AsyncMock(side_effect=lambda meta: written_meta.append(meta)),
        ):
            result = await runtime.await_shell("abc123", block_until_ms=0)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_delta, "xyz")
        self.assertEqual(len(written_meta), 2)
        self.assertEqual(written_meta[0].status, "completed")
        self.assertEqual(written_meta[1].last_delivered_offset, 7)
