import types
import unittest
import uuid
from unittest.mock import patch

from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.local_docker import LocalDockerSandbox


class DummyJupyterSandbox(JupyterSandbox):
    async def stop(self) -> None:
        return None


class InternalDummyJupyterSandbox(DummyJupyterSandbox):
    def is_base_url_internal(self) -> bool:
        return True


class JupyterSandboxProxySettingsTests(unittest.TestCase):
    def test_base_url_is_external_by_default(self):
        runtime = DummyJupyterSandbox(base_url="http://example.com")

        self.assertFalse(runtime.is_base_url_internal())
        self.assertEqual(runtime._get_client_session_kwargs(), {})
        self.assertEqual(runtime._get_websocket_connect_kwargs(), {})

    def test_internal_base_url_disables_proxy_for_http_and_websocket(self):
        runtime = InternalDummyJupyterSandbox(base_url="http://internal.example")

        self.assertTrue(runtime.is_base_url_internal())
        self.assertEqual(runtime._get_client_session_kwargs(), {"trust_env": False})
        self.assertEqual(runtime._get_websocket_connect_kwargs(), {"proxy": None})

    def test_local_docker_reports_internal_base_url_when_docker_network_enabled(self):
        runtime = LocalDockerSandbox.model_construct(
            base_url="http://giga-sandbox-test:8888",
            sandbox_id=uuid.uuid4(),
            host_port=None,
        )

        with patch(
            "giga_agent.sandbox.local_docker.get_settings",
            return_value=types.SimpleNamespace(giga_agent_docker_network="sandbox-net"),
        ):
            self.assertTrue(runtime.is_base_url_internal())

    def test_local_docker_reports_external_base_url_without_docker_network(self):
        runtime = LocalDockerSandbox.model_construct(
            base_url="http://localhost:12345",
            sandbox_id=uuid.uuid4(),
            host_port=12345,
        )

        with patch(
            "giga_agent.sandbox.local_docker.get_settings",
            return_value=types.SimpleNamespace(giga_agent_docker_network=None),
        ):
            self.assertFalse(runtime.is_base_url_internal())
