import os
import unittest
from contextlib import contextmanager
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
