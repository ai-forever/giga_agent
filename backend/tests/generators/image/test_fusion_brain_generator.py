import unittest
from unittest.mock import AsyncMock

from giga_agent.generators.image.base import DEFAULT_HEIGHT, DEFAULT_WIDTH
from giga_agent.generators.image.fusion_brain import FusionBrainImageGen


class FusionBrainImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_normalizes_none_dimensions(self):
        gen = FusionBrainImageGen(api_key="key", secret_key="secret")
        await gen.init()
        gen._api.generate_and_get_image = AsyncMock(return_value=["image-b64"])

        result = await gen.generate_image("prompt", None, None)

        self.assertEqual(result, "image-b64")
        gen._api.generate_and_get_image.assert_awaited_once_with(
            "prompt",
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
        )
