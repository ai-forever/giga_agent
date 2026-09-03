import os
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import jwt

from giga_agent.conf import reset_settings_cache
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

    def _decode_exp(self, token: str, secret: str) -> datetime:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        self.assertIn("exp", payload)
        return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    def test_token_has_exp_by_default(self):
        user_id = uuid.uuid4()
        with self._patched_env(
            {
                "GIGA_AGENT_SECRET_KEY": "new-secret",
                "GIGA_AGENT_AUTH_ALGORITHM": "HS256",
            },
            clear=True,
        ):
            token = security.create_access_token({"user_id": str(user_id)})
            expire_at = self._decode_exp(token, "new-secret")
            self.assertGreater(expire_at, datetime.now(timezone.utc))

    def test_token_expire_minutes_configurable(self):
        user_id = uuid.uuid4()
        with self._patched_env(
            {
                "GIGA_AGENT_SECRET_KEY": "new-secret",
                "GIGA_AGENT_AUTH_ALGORITHM": "HS256",
                "GIGA_AGENT_ACCESS_TOKEN_EXPIRE_MINUTES": "60",
            },
            clear=True,
        ):
            token = security.create_access_token({"user_id": str(user_id)})
            expire_at = self._decode_exp(token, "new-secret")
            delta_minutes = (
                expire_at - datetime.now(timezone.utc)
            ).total_seconds() / 60
            self.assertGreater(delta_minutes, 59)
            self.assertLess(delta_minutes, 61)
