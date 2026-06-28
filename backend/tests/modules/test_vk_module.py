import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.modules.vk import VKModule
from giga_agent.modules.vk.provider import build_vk_provider


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResp(self._data)


def _patch_vk_http(data):
    return patch(
        "giga_agent.modules.vk.provider.httpx.AsyncClient",
        lambda **_: _FakeClient(data),
    )


class VKModuleTests(unittest.IsolatedAsyncioTestCase):
    def test_get_secrets_contract(self):
        module = VKModule()
        self.assertEqual(
            module.get_secrets(),
            [
                {
                    "name": "VK_TOKEN",
                    "description": "Токен VK API для чтения постов и комментариев.",
                    "type": "pass",
                }
            ],
        )

    async def test_get_tools_empty_because_lazy(self):
        # VK is a lazy module: its tools are delivered via the connector
        # meta-tools, not bound — so get_tools is always empty.
        module = VKModule()
        for secrets in ({}, {"VK_TOKEN": "token"}):
            user = types.SimpleNamespace(secrets=secrets)
            tools = await module.get_tools(user=user, agent=object())
            self.assertEqual(tools, [])

    async def test_get_tool_sources_hidden_without_secret(self):
        module = VKModule()
        user = types.SimpleNamespace(secrets={})
        sources = await module.get_tool_sources(user=user, agent=object())
        self.assertEqual(sources, [])

    async def test_get_tool_sources_available_with_secret(self):
        module = VKModule()
        user = types.SimpleNamespace(secrets={"VK_TOKEN": "token"})
        sources = await module.get_tool_sources(user=user, agent=object())
        self.assertEqual(len(sources), 1)
        source = sources[0]
        self.assertEqual(source.name, "vk")
        specs = await source.list_tools(user_id=uuid.uuid4())
        self.assertEqual(
            sorted(s.name for s in specs),
            sorted(["vk_get_posts", "vk_get_comments", "vk_get_last_comments"]),
        )

    def test_provider_contract(self):
        provider = build_vk_provider()
        info = provider.info()
        self.assertEqual(info.key, "vk")
        self.assertEqual(info.auth_kind, "manual_token")
        self.assertEqual([f.key for f in info.manual_fields], ["token"])


class VKTokenValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_true_on_response(self):
        provider = build_vk_provider()
        with _patch_vk_http({"response": [{"id": 1}]}):
            self.assertTrue(await provider.validate("good-token"))

    async def test_validate_false_on_error(self):
        provider = build_vk_provider()
        with _patch_vk_http({"error": {"error_code": 5}}):
            self.assertFalse(await provider.validate("bad-token"))

    async def test_store_manual_token_rejects_invalid(self):
        provider = build_vk_provider()
        # validate() fails → store raises BEFORE touching the DB.
        with patch.object(provider, "validate", AsyncMock(return_value=False)):
            with self.assertRaisesRegex(ValueError, "недействителен"):
                await provider.store_manual_token(
                    user_id=uuid.uuid4(), fields={"token": "bad"}
                )
