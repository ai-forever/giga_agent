import os
import types
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.sandbox_redirect import router

HEX = "ab" * 16  # 32 hex chars
PORT = 8501


class SandboxRedirectRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.user = types.SimpleNamespace(
            id=self.owner_id, is_active=True, is_superuser=False
        )
        self.db = types.SimpleNamespace()
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_get_session():
            yield self.db

        self.app.dependency_overrides[get_session] = _override_get_session
        # Do not follow redirects: we want to inspect the 302 Location.
        self.client = TestClient(self.app, follow_redirects=False)

    def _override_user(self, user) -> None:
        async def _override():
            return user

        self.app.dependency_overrides[get_current_active_user] = _override

    @contextmanager
    def _patched_env(self, values: dict[str, str]):
        reset_settings_cache()
        with patch.dict(os.environ, values):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

    @contextmanager
    def _patched_backend(self, *, owner_id):
        with (
            patch(
                "giga_agent.routes.sandbox_redirect.SandboxRepository."
                "get_owner_id_by_sandbox_cached",
                AsyncMock(return_value=owner_id),
            ),
            patch(
                "giga_agent.routes.sandbox_redirect.mint_sandbox_access_token",
                AsyncMock(return_value="TESTTOKEN"),
            ),
        ):
            yield

    def test_mode_disabled_returns_404(self):
        self._override_user(self.user)
        with self._patched_env({}), self._patched_backend(owner_id=self.owner_id):
            # Ensure the flag is absent.
            os.environ.pop("GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE", None)
            reset_settings_cache()
            resp = self.client.get(f"/sandbox-redirect/{HEX}/{PORT}")
        self.assertEqual(resp.status_code, 404)

    def test_no_session_returns_401(self):
        # No get_current_active_user override → real cookie auth runs; no cookie.
        with (
            self._patched_env({"GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE": "gigapp.ru"}),
            self._patched_backend(owner_id=self.owner_id),
        ):
            resp = self.client.get(f"/sandbox-redirect/{HEX}/{PORT}")
        self.assertEqual(resp.status_code, 401)

    def test_not_owner_returns_403(self):
        self._override_user(self.user)
        with (
            self._patched_env({"GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE": "gigapp.ru"}),
            self._patched_backend(owner_id=uuid.uuid4()),
        ):  # different owner
            resp = self.client.get(f"/sandbox-redirect/{HEX}/{PORT}")
        self.assertEqual(resp.status_code, 403)

    def test_unknown_sandbox_returns_404(self):
        self._override_user(self.user)
        with (
            self._patched_env({"GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE": "gigapp.ru"}),
            self._patched_backend(owner_id=None),
        ):
            resp = self.client.get(f"/sandbox-redirect/{HEX}/{PORT}")
        self.assertEqual(resp.status_code, 404)

    def test_bad_hex_returns_404(self):
        self._override_user(self.user)
        with (
            self._patched_env({"GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE": "gigapp.ru"}),
            self._patched_backend(owner_id=self.owner_id),
        ):
            resp = self.client.get(f"/sandbox-redirect/not-a-hex/{PORT}")
        self.assertEqual(resp.status_code, 404)

    def test_owner_gets_302_to_sandbox_with_token(self):
        self._override_user(self.user)
        with (
            self._patched_env({"GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE": "GigApp.RU."}),
            self._patched_backend(owner_id=self.owner_id),
        ):
            resp = self.client.get(f"/sandbox-redirect/{HEX}/{PORT}")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.headers["location"],
            f"https://{PORT}-sandbox-{HEX}.gigapp.ru/?__sbx=TESTTOKEN",
        )


if __name__ == "__main__":
    unittest.main()
