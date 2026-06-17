import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.runtime_config import mount_runtime_config_route
from giga_agent.ui import mount_ui


class RuntimeConfigRouteTests(unittest.TestCase):
    def test_root_route_serves_runtime_config_independent_of_ui_mount(self):
        app = FastAPI()
        mount_runtime_config_route(app)

        client = TestClient(app)
        with (
            patch("giga_agent.runtime_config.GIGA_AGENT_BASE_URL", None),
            patch("giga_agent.runtime_config.GIGA_AGENT_UI_PREFIX", "/ui"),
            patch("giga_agent.runtime_config.GIGA_AGENT_PREFIX_API", "/agent"),
            patch("giga_agent.runtime_config.GIGA_AGENT_RUNTIME_LOCAL", True),
            patch("giga_agent.runtime_config.GIGA_AGENT_SKIP_ONBOARDING", True),
        ):
            response = client.get("/app-config.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/javascript")
        payload = self._read_runtime_payload(response.text)
        self.assertEqual(payload["basePath"], "/ui/")
        self.assertEqual(payload["apiBasePath"], "/ui/api")
        self.assertEqual(payload["apiAgentBasePath"], "/ui/api/agent")
        self.assertTrue(payload["runtimeLocal"])
        self.assertTrue(payload["skipOnboarding"])

    def test_ui_mount_keeps_prefixed_app_config_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            index = Path(tmp_dir) / "index.html"
            index.write_text(
                '<html><head><base href="/"/></head><body>ok</body></html>'
            )

            app = FastAPI()
            with (
                patch("giga_agent.ui.GIGA_AGENT_FRONTEND_DIR", tmp_dir),
                patch("giga_agent.ui.GIGA_AGENT_UI_PREFIX", "/ui"),
            ):
                mount_ui(app)

            client = TestClient(app)
            with (
                patch("giga_agent.runtime_config.GIGA_AGENT_BASE_URL", None),
                patch("giga_agent.runtime_config.GIGA_AGENT_UI_PREFIX", "/ui"),
                patch("giga_agent.runtime_config.GIGA_AGENT_PREFIX_API", "/agent"),
                patch("giga_agent.runtime_config.GIGA_AGENT_RUNTIME_LOCAL", False),
                patch("giga_agent.runtime_config.GIGA_AGENT_SKIP_ONBOARDING", False),
            ):
                response = client.get("/ui/app-config.js")
                index_response = client.get("/ui/")

        self.assertEqual(response.status_code, 200)
        payload = self._read_runtime_payload(response.text)
        self.assertEqual(payload["basePath"], "/ui/")
        self.assertEqual(payload["apiBasePath"], "/ui/api")
        self.assertFalse(payload["runtimeLocal"])
        self.assertFalse(payload["skipOnboarding"])
        self.assertEqual(index_response.status_code, 200)
        self.assertIn('<base href="/ui/"/>', index_response.text)

    @staticmethod
    def _read_runtime_payload(script_body: str) -> dict[str, str | bool]:
        prefix = "window.__GIGA_AGENT_CONFIG__ = "
        assert script_body.startswith(prefix)
        assert script_body.endswith(";")
        return json.loads(script_body[len(prefix) : -1])
