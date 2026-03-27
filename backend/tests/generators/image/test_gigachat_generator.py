import base64
import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.conf import reset_settings_cache
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
    def setUp(self) -> None:
        reset_settings_cache()

    def tearDown(self) -> None:
        reset_settings_cache()

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
        token_cache_mock.assert_awaited_once_with(
            connector,
            api_object=llm_stub,
            force_refresh=False,
        )

    async def test_skip_cache_token_uses_uncached_token_for_init(self):
        gigachat_client = types.SimpleNamespace(
            aget_token=AsyncMock(
                return_value=types.SimpleNamespace(access_token="token-from-connector")
            ),
            _client=types.SimpleNamespace(base_url="https://gigachat.devices.sberbank.ru/api/v1"),
        )
        llm_stub = types.SimpleNamespace(_client=gigachat_client)
        connector = GigaChatConnector()
        token_cache_mock = AsyncMock(return_value="cached-token")
        token_uncached_mock = AsyncMock(return_value="token-from-connector")

        with patch.dict(
            "os.environ",
            {"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"},
            clear=False,
        ):
            reset_settings_cache()
            with patch.object(
                GigaChatConnector,
                "get_api_object",
                return_value=llm_stub,
            ), patch(
                "giga_agent.generators.image.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch(
                "giga_agent.generators.image.gigachat.get_gigachat_access_token_uncached",
                token_uncached_mock,
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
        token_cache_mock.assert_not_awaited()
        token_uncached_mock.assert_awaited_once_with(connector, api_object=llm_stub)

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
        token_cache_mock.assert_awaited_once_with(
            connector,
            api_object=llm_stub,
            force_refresh=False,
        )

    async def test_skip_cache_token_refreshes_uncached_after_401(self):
        gigachat_client = types.SimpleNamespace(
            aget_token=AsyncMock(
                return_value=types.SimpleNamespace(access_token="token-from-connector")
            ),
            _client=types.SimpleNamespace(base_url="https://gigachat.devices.sberbank.ru/api/v1"),
        )
        llm_stub = types.SimpleNamespace(_client=gigachat_client)
        connector = GigaChatConnector()
        token_cache_mock = AsyncMock(return_value="cached-token")
        token_uncached_mock = AsyncMock(side_effect=["token-1", "token-2"])

        unauthorized = types.SimpleNamespace(status_code=401, is_success=False)
        success = _SuccessResponse()
        seen_authorizations: list[str] = []

        async def _post_side_effect(*args, **kwargs):
            seen_authorizations.append(kwargs["headers"]["Authorization"])
            if len(seen_authorizations) == 1:
                return unauthorized
            return success

        with patch.dict(
            "os.environ",
            {"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"},
            clear=False,
        ):
            reset_settings_cache()
            with patch.object(
                GigaChatConnector,
                "get_api_object",
                return_value=llm_stub,
            ), patch(
                "giga_agent.generators.image.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch(
                "giga_agent.generators.image.gigachat.get_gigachat_access_token_uncached",
                token_uncached_mock,
            ):
                gen = GigaChatImageGen(connector=connector)
                try:
                    await gen.init()
                    gen._client.post = AsyncMock(side_effect=_post_side_effect)
                    result = await gen.generate_image("prompt", 1024, 1024)
                finally:
                    if gen._client is not None:
                        await gen._client.aclose()

        self.assertEqual(result, base64.b64encode(b"image-bytes").decode("ascii"))
        token_cache_mock.assert_not_awaited()
        self.assertEqual(token_uncached_mock.await_count, 2)
        token_uncached_mock.assert_any_await(connector, api_object=llm_stub)
        token_uncached_mock.assert_any_await(connector, api_object=None)
        self.assertEqual(gen._client.post.await_count, 2)
        self.assertEqual(seen_authorizations, ["Bearer token-1", "Bearer token-2"])
