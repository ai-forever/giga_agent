import os
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.local_docker import LocalDockerSandbox
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
                "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(ping=lambda: None, close=lambda: None),
        ):
            validated = await LocalDockerSandbox.validate_settings({})
        self.assertEqual(validated["image"], "registry.example/custom-sandbox:1.2.3")

    async def test_validate_settings_fails_when_docker_unreachable(self):
        with self._patched_env(
            {"GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES": "3"},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            side_effect=RuntimeError("daemon unavailable"),
        ):
            with self.assertRaisesRegex(ValueError, "Docker connection check failed"):
                await LocalDockerSandbox.validate_settings({})

    async def test_requires_running_for_read_delete(self):
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(owner_id=owner_id, max_active_sandboxes=1)
            with patch.object(runtime, "_random_key_suffix", return_value="ABCDEFGH"):
                rel = runtime._uniquify_bucket_rel_path(
                    owner_id=owner_id,
                    file_name="thread-42/reports/report.txt",
                )

        self.assertEqual(rel.as_posix(), "thread-42/reports/report--ABCDEFGH.txt")

    def _fake_container(self, host_port: str = "12345"):
        # sandbox-server публикуется на порту 49999 внутри контейнера
        return types.SimpleNamespace(
            id="container-1",
            attrs={
                "NetworkSettings": {"Ports": {"49999/tcp": [{"HostPort": host_port}]}}
            },
            reload=lambda: None,
        )

    async def test_up_passes_management_labels_to_container(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        run_mock = Mock(return_value=self._fake_container())
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(run=run_mock)
        )

        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=client,
        ), patch.object(
            LocalDockerSandbox, "_ensure_api_server_ready", new=AsyncMock()
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

    async def test_up_runs_sandbox_server_and_sets_api_base_url(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        run_mock = Mock(return_value=self._fake_container())
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(run=run_mock)
        )

        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=client,
        ), patch.object(
            LocalDockerSandbox, "_ensure_api_server_ready", new=AsyncMock()
        ):
            runtime = LocalDockerSandbox(
                owner_id=owner_id,
                provider_id=provider_id,
                sandbox_id=sandbox_id,
                max_active_sandboxes=1,
            )
            await runtime.up()

        kwargs = run_mock.call_args.kwargs
        self.assertEqual(kwargs["command"], ["sandbox-server-supervised"])
        self.assertIn("49999/tcp", kwargs["ports"])
        self.assertEqual(kwargs["environment"]["SANDBOX_API_TOKEN"], runtime.api_token)
        self.assertEqual(kwargs["environment"]["SANDBOX_API_PORT"], "49999")
        self.assertTrue(runtime.api_token)
        self.assertEqual(runtime.api_base_url, "http://localhost:12345")

    async def test_is_up_uses_container_liveness(self):
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
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

    _MB = 1024 * 1024

    def _reconcile_runtime(self):
        with patch(
            "giga_agent.sandbox.local_docker.runtime.docker.from_env",
            return_value=types.SimpleNamespace(),
        ):
            runtime = LocalDockerSandbox(
                max_active_sandboxes=1,
                image="giga/sandbox:1.0",
                memory_limit_mb=512,
                memory_reservation_mb=256,
                vcpu=1.0,
                pids_limit=200,
                shm_size_mb=64,
                nofile_soft=1024,
                nofile_hard=2048,
                enforce_readonly_rootfs=False,
                not_remove=False,
            )
        runtime.external_id = "container-1"
        runtime._ensure_container_connected = AsyncMock(return_value=None)
        api = types.SimpleNamespace(
            _url=Mock(return_value="/containers/container-1/update"),
            _post_json=Mock(return_value=Mock()),
            _raise_for_status=Mock(),
        )
        runtime._client = types.SimpleNamespace(api=api)
        return runtime, api

    def _matching_attrs(self):
        return {
            "Config": {"Image": "giga/sandbox:1.0"},
            "HostConfig": {
                "Memory": 512 * self._MB,
                "MemoryReservation": 256 * self._MB,
                "NanoCpus": 1_000_000_000,
                "PidsLimit": 200,
                "ShmSize": 64 * self._MB,
                "ReadonlyRootfs": False,
                "AutoRemove": True,  # not_remove=False → --rm
                "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 2048}],
            },
        }

    async def test_reconcile_noop_when_config_matches(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        runtime, api = self._reconcile_runtime()
        runtime._container = types.SimpleNamespace(
            reload=Mock(), attrs=self._matching_attrs()
        )

        outcome = await runtime.reconcile_runtime_settings()

        self.assertIs(outcome, RuntimeReconcileOutcome.NOOP)
        api._post_json.assert_not_called()

    async def test_reconcile_hot_update_on_memory_change(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        runtime, api = self._reconcile_runtime()
        attrs = self._matching_attrs()
        attrs["HostConfig"]["Memory"] = 256 * self._MB  # дрейф лимита памяти
        runtime._container = types.SimpleNamespace(reload=Mock(), attrs=attrs)

        outcome = await runtime.reconcile_runtime_settings()

        self.assertIs(outcome, RuntimeReconcileOutcome.HOT_UPDATED)
        api._post_json.assert_called_once()
        body = api._post_json.call_args.kwargs["data"]
        self.assertEqual(body["Memory"], 512 * self._MB)
        self.assertEqual(body["MemoryReservation"], 256 * self._MB)
        self.assertEqual(body["NanoCpus"], 1_000_000_000)
        self.assertEqual(body["PidsLimit"], 200)

    async def test_reconcile_recreate_on_image_change(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        runtime, api = self._reconcile_runtime()
        attrs = self._matching_attrs()
        attrs["Config"]["Image"] = "giga/sandbox:0.9"  # холодное поле
        runtime._container = types.SimpleNamespace(reload=Mock(), attrs=attrs)

        outcome = await runtime.reconcile_runtime_settings()

        self.assertIs(outcome, RuntimeReconcileOutcome.RECREATE)
        api._post_json.assert_not_called()

    async def test_reconcile_recreate_on_shm_change(self):
        from giga_agent.sandbox.base import RuntimeReconcileOutcome

        runtime, api = self._reconcile_runtime()
        attrs = self._matching_attrs()
        attrs["HostConfig"]["ShmSize"] = 128 * self._MB  # холодное поле
        runtime._container = types.SimpleNamespace(reload=Mock(), attrs=attrs)

        outcome = await runtime.reconcile_runtime_settings()

        self.assertIs(outcome, RuntimeReconcileOutcome.RECREATE)
        api._post_json.assert_not_called()

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
