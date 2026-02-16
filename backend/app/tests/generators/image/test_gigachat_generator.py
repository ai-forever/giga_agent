import base64
import types
import unittest
from unittest.mock import AsyncMock

from giga_agent.generators.image.gigachat import GigaChatImageGen


class _SuccessResponse:
    status_code = 200
    is_success = True
    content = b"image-bytes"

    @staticmethod
    def raise_for_status() -> None:
        return None


class GigaChatImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_llm_client_for_token(self):
        gigachat_client = types.SimpleNamespace(
            aget_token=AsyncMock(return_value=types.SimpleNamespace(access_token="token-from-llm")),
            _client=types.SimpleNamespace(base_url="https://gigachat.devices.sberbank.ru/api/v1"),
        )
        llm_stub = types.SimpleNamespace(_client=gigachat_client)

        gen = GigaChatImageGen()
        gen.llm = llm_stub

        try:
            await gen.init()
            gen._client.post = AsyncMock(return_value=_SuccessResponse())
            result = await gen.generate_image("prompt", 1024, 1024)
        finally:
            if gen._client is not None:
                await gen._client.aclose()

        self.assertEqual(result, base64.b64encode(b"image-bytes").decode("ascii"))
        gigachat_client.aget_token.assert_awaited_once()

    async def test_init_fails_without_llm(self):
        gen = GigaChatImageGen()

        with self.assertRaises(ValueError):
            await gen.init()
