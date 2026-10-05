import os
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from giga_agent.conf import get_settings, reset_settings_cache
from giga_agent.modules.auth import security


class AuthSecuritySettingsTests(unittest.TestCase):
    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    def test_jwt_uses_new_secret_and_algorithm_envs(self):
        user_id = uuid.uuid4()
        with self._patched_env(
            {
                "GIGA_AGENT_SECRET_KEY": "new-secret",
                "GIGA_AGENT_AUTH_ALGORITHM": "HS256",
                "SECRET_KEY": "legacy-secret",
                "ALGORITHM": "HS512",
            },
            clear=True,
        ):
            token = security.create_access_token({"user_id": str(user_id)})
            decoded_user_id = security.get_user_id_from_token(token)
            self.assertEqual(decoded_user_id, user_id)

    def test_admin_password_not_set_generates_random(self):
        # Без явного пароля (None или пустая строка) генерируется криптостойкий
        # случайный, а не общеизвестный дефолт (H4).
        for unset in (None, ""):
            password, generated = security.resolve_admin_password(unset)
            self.assertTrue(generated)
            self.assertIsInstance(password, str)
            self.assertGreaterEqual(len(password), 16)

    def test_admin_password_explicit_not_generated(self):
        password, generated = security.resolve_admin_password("my-secret-password")
        self.assertFalse(generated)
        self.assertEqual(password, "my-secret-password")

    def test_admin_password_default_config_is_none(self):
        with self._patched_env({}, clear=True):
            self.assertIsNone(get_settings().giga_agent_admin_password)
