import unittest

from giga_agent.sandbox.jupyter import JupyterSandbox


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
