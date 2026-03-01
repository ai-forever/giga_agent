import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.generators.image.openai import OpenAIImageGen


class OpenAIImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_connector_api_object_root_async_client(self):
        connector = OpenAIConnector(api_key="test-key")
        llm = connector.get_api_object()
        mock_generate = AsyncMock(
            return_value=types.SimpleNamespace(
                data=[types.SimpleNamespace(b64_json="from-llm-client")]
            )
        )

        # Важно: OpenAIImageGen.init() вызывает connector.get_api_object() ещё раз.
        # Поэтому фиксируем один и тот же api_object, иначе мок окажется на другом клиенте.
        with patch.object(OpenAIConnector, "get_api_object", return_value=llm):
            with patch.object(llm.root_async_client.images, "generate", mock_generate):
                gen = OpenAIImageGen(connector=connector)
                await gen.init()
                result = await gen.generate_image("prompt", 1024, 1024)

        self.assertEqual(result, "from-llm-client")
        mock_generate.assert_awaited_once()
        await llm.root_async_client.close()

    async def test_init_fails_without_connector(self):
        gen = OpenAIImageGen()

        with self.assertRaises(ValueError):
            await gen.init()
