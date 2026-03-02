import os
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from giga_agent.conf import reset_settings_cache
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.local_docker import LocalDockerSandbox


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

            sandbox_path = await runtime.upload_file(
                owner_id=owner_id,
                file_name="notes/report.txt",
                content=b"hello",
            )
            self.assertEqual(sandbox_path, "/bucket/notes/report.txt")

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
