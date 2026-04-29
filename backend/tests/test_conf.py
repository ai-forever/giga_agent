import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from giga_agent.conf import get_settings, reset_settings_cache


class ConfSettingsTests(unittest.TestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    def test_reads_giga_agent_secret_key(self):
        with self._patched_env({"GIGA_AGENT_SECRET_KEY": "new-secret"}, clear=False):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_secret_key, "new-secret")

    def test_ignores_legacy_secret_key_env(self):
        with self._patched_env({"SECRET_KEY": "legacy-secret"}, clear=True):
            settings = get_settings()
            self.assertNotEqual(settings.giga_agent_secret_key, "legacy-secret")

    def test_settings_cache_and_reset(self):
        with self._patched_env({"GIGA_AGENT_SECRET_KEY": "first"}, clear=True):
            first = get_settings()
            second = get_settings()
            self.assertIs(first, second)
            self.assertEqual(first.giga_agent_secret_key, "first")

        with self._patched_env({"GIGA_AGENT_SECRET_KEY": "second"}, clear=True):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_secret_key, "second")

    def test_reads_giga_agent_log_level(self):
        with self._patched_env({"GIGA_AGENT_LOG_LEVEL": "debug"}, clear=True):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_log_level, "DEBUG")

    def test_uses_default_log_level(self):
        with self._patched_env({}, clear=True):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_log_level, "INFO")

    def test_gigachat_from_env_disabled_by_default(self):
        with self._patched_env({}, clear=True):
            settings = get_settings()
            self.assertFalse(settings.giga_agent_gigachat_from_env)

    def test_reads_gigachat_from_env_flag(self):
        with self._patched_env({"GIGA_AGENT_GIGACHAT_FROM_ENV": "1"}, clear=True):
            settings = get_settings()
            self.assertTrue(settings.giga_agent_gigachat_from_env)

    def test_gigachat_skip_cache_token_disabled_by_default(self):
        with self._patched_env({}, clear=True):
            settings = get_settings()
            self.assertFalse(settings.giga_agent_gigachat_skip_cache_token)

    def test_reads_gigachat_skip_cache_token_flag(self):
        with self._patched_env({"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"}, clear=True):
            settings = get_settings()
            self.assertTrue(settings.giga_agent_gigachat_skip_cache_token)

    def test_runtime_local_disabled_by_default(self):
        with self._patched_env({}, clear=True):
            settings = get_settings()
            self.assertFalse(settings.giga_agent_runtime_local)

    def test_reads_runtime_local_flag(self):
        with self._patched_env({"GIGA_AGENT_RUNTIME_LOCAL": "1"}, clear=True):
            settings = get_settings()
            self.assertTrue(settings.giga_agent_runtime_local)

    def test_local_jupyter_deny_read_roots_empty_by_default(self):
        with self._patched_env({}, clear=True):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_local_jupyter_deny_read_roots, [])

    def test_reads_local_jupyter_settings(self):
        with self._patched_env(
            {
                "GIGA_AGENT_LOCAL_JUPYTER_STARTUP_TIMEOUT_SEC": "42",
                "GIGA_AGENT_LOCAL_JUPYTER_GRACEFUL_SHUTDOWN_TIMEOUT_SEC": "7",
                "GIGA_AGENT_LOCAL_JUPYTER_WORKING_DIR": "~/workdir",
                "GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH": "~/files",
                "GIGA_AGENT_LOCAL_JUPYTER_RUNTIME_DIR": "~/runtime",
                "GIGA_AGENT_LOCAL_JUPYTER_PYTHON_EXECUTABLE": "/usr/bin/python3",
                "GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_DEFAULT": "1",
                "GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_BACKEND": "linux_bwrap",
                "GIGA_AGENT_LOCAL_JUPYTER_ALLOWED_READ_ROOTS": '["/"]',
                "GIGA_AGENT_LOCAL_JUPYTER_ALLOWED_WRITE_ROOTS": '["/tmp/write"]',
                "GIGA_AGENT_LOCAL_JUPYTER_DENY_READ_ROOTS": '["~/.ssh"]',
                "GIGA_AGENT_LOCAL_JUPYTER_NETWORK_MODE": "none",
            },
            clear=True,
        ):
            settings = get_settings()
            self.assertEqual(settings.giga_agent_local_jupyter_startup_timeout_sec, 42)
            self.assertEqual(
                settings.giga_agent_local_jupyter_graceful_shutdown_timeout_sec,
                7,
            )
            self.assertTrue(str(settings.giga_agent_local_jupyter_working_dir).endswith("workdir"))
            self.assertTrue(str(settings.giga_agent_local_jupyter_files_path).endswith("files"))
            self.assertTrue(str(settings.giga_agent_local_jupyter_runtime_dir).endswith("runtime"))
            self.assertEqual(
                settings.giga_agent_local_jupyter_python_executable,
                "/usr/bin/python3",
            )
            self.assertTrue(settings.giga_agent_local_jupyter_secure_exec_default)
            self.assertEqual(
                settings.giga_agent_local_jupyter_secure_exec_backend,
                "linux_bwrap",
            )
            self.assertEqual(settings.giga_agent_local_jupyter_allowed_read_roots, [Path("/")])
            self.assertEqual(
                settings.giga_agent_local_jupyter_allowed_write_roots,
                [Path("/tmp/write")],
            )
            self.assertEqual(
                settings.giga_agent_local_jupyter_deny_read_roots,
                [Path("~/.ssh").expanduser()],
            )
            self.assertEqual(settings.giga_agent_local_jupyter_network_mode, "none")
