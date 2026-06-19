import unittest
from unittest.mock import AsyncMock

from giga_agent.generators.image.base import DEFAULT_HEIGHT, DEFAULT_WIDTH
from giga_agent.generators.image.fusion_brain import FusionBrainImageGen


class FusionBrainImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_normalizes_none_dimensions(self):
        gen = FusionBrainImageGen(api_key="key", secret_key="secret")
        await gen.init()
        gen._api.generate_and_get_image = AsyncMock(return_value=["image-b64"])

        try:
            result = await gen.generate_image("prompt", None, None)
        finally:
            await gen.cleanup()

        self.assertEqual(result, "image-b64")
        gen._api.generate_and_get_image.assert_awaited_once_with(
            "prompt",
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
        )

    async def test_cleanup_closes_client(self):
        gen = FusionBrainImageGen(api_key="key", secret_key="secret")
        await gen.init()
        client = gen._api.client
        self.assertFalse(client.is_closed)

        await gen.cleanup()

        self.assertTrue(client.is_closed)

    async def test_cleanup_is_safe_without_init(self):
        gen = FusionBrainImageGen(api_key="key", secret_key="secret")
        # cleanup should not raise even if init was never called
        await gen.cleanup()
