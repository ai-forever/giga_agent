import base64
import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.connectors.gigachat import GigaChatConnector
from giga_agent.generators.image.base import DEFAULT_HEIGHT, DEFAULT_WIDTH
from giga_agent.generators.image.gigachat import GigaChatImageGen


class _SuccessResponse:
    status_code = 200
    is_success = True
    content = b"image-bytes"

    @staticmethod
    def raise_for_status() -> None:
        return None


class GigaChatImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_connector_api_object_for_token(self):
        gigachat_client = types.SimpleNamespace(
            aget_token=AsyncMock(return_value=types.SimpleNamespace(access_token="token-from-connector")),
            _client=types.SimpleNamespace(base_url="https://gigachat.devices.sberbank.ru/api/v1"),
        )
        llm_stub = types.SimpleNamespace(_client=gigachat_client)
        connector = GigaChatConnector()

        token_cache_mock = AsyncMock(return_value="token-from-connector")

        with patch.object(
            GigaChatConnector,
            "get_api_object",
            return_value=llm_stub,
        ), patch(
            "giga_agent.generators.image.gigachat.get_gigachat_access_token_cached",
            token_cache_mock,
        ):
            gen = GigaChatImageGen(connector=connector)
            try:
                await gen.init()
                gen._client.post = AsyncMock(return_value=_SuccessResponse())
                result = await gen.generate_image("prompt", 1024, 1024)
            finally:
                if gen._client is not None:
                    await gen._client.aclose()

        self.assertEqual(result, base64.b64encode(b"image-bytes").decode("ascii"))
        token_cache_mock.assert_awaited_once_with(connector, api_object=llm_stub)

    async def test_init_fails_without_connector(self):
        gen = GigaChatImageGen()

        with self.assertRaises(ValueError):
            await gen.init()

    async def test_generate_image_normalizes_none_dimensions(self):
        gigachat_client = types.SimpleNamespace(
            aget_token=AsyncMock(return_value=types.SimpleNamespace(access_token="token-from-connector")),
            _client=types.SimpleNamespace(base_url="https://gigachat.devices.sberbank.ru/api/v1"),
        )
        llm_stub = types.SimpleNamespace(_client=gigachat_client)
        connector = GigaChatConnector()

        token_cache_mock = AsyncMock(return_value="token-from-connector")

        with patch.object(
            GigaChatConnector,
            "get_api_object",
            return_value=llm_stub,
        ), patch(
            "giga_agent.generators.image.gigachat.get_gigachat_access_token_cached",
            token_cache_mock,
        ):
            gen = GigaChatImageGen(connector=connector)
            try:
                await gen.init()
                gen._client.post = AsyncMock(return_value=_SuccessResponse())
                result = await gen.generate_image("prompt", None, None)
            finally:
                if gen._client is not None:
                    await gen._client.aclose()

        self.assertEqual(result, base64.b64encode(b"image-bytes").decode("ascii"))
        gen._client.post.assert_awaited_once_with(
            "/image/generate",
            json={
                "mode": "kandinsky-4.1:image",
                "query": "prompt",
                "model_params": {
                    "width": DEFAULT_WIDTH,
                    "height": DEFAULT_HEIGHT,
                },
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer token-from-connector",
            },
        )
        token_cache_mock.assert_awaited_once_with(connector, api_object=llm_stub)
