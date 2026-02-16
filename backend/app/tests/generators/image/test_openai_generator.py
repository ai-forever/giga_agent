import types
import unittest
from unittest.mock import AsyncMock, patch

from langchain_openai import ChatOpenAI

from giga_agent.generators.image.openai import OpenAIImageGen


class OpenAIImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_llm_root_async_client(self):
        llm = ChatOpenAI(model="gpt-4o-mini", api_key="test-key")
        mock_generate = AsyncMock(
            return_value=types.SimpleNamespace(
                data=[types.SimpleNamespace(b64_json="from-llm-client")]
            )
        )

        with patch.object(llm.root_async_client.images, "generate", mock_generate):
            gen = OpenAIImageGen(llm=llm)
            await gen.init()
            result = await gen.generate_image("prompt", 1024, 1024)

        self.assertEqual(result, "from-llm-client")
        mock_generate.assert_awaited_once()
        await llm.root_async_client.close()

    async def test_init_fails_without_llm(self):
        gen = OpenAIImageGen()

        with self.assertRaises(ValueError):
            await gen.init()
