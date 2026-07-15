import types
import unittest
from unittest.mock import AsyncMock

from giga_agent.generators.image.grok.generator import GrokImagineImageGen


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class GrokImagineImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_uses_generations_endpoint(self):
        gen = GrokImagineImageGen(api_key="test-key", model="grok-imagine")
        gen._client = types.SimpleNamespace(
            post=AsyncMock(
                return_value=_FakeResponse({"data": [{"b64_json": "img-b64"}]})
            )
        )
        gen._initialized = True

        result = await gen.generate_image(
            "prompt",
            None,
            None,
            aspect_ratio="16:9",
            resolution="2k",
        )

        self.assertEqual(result, "img-b64")
        gen._client.post.assert_awaited_once()
        self.assertEqual(gen._client.post.await_args.args[0], "/images/generations")
        payload = gen._client.post.await_args.kwargs["json"]
        self.assertEqual(payload["model"], "grok-imagine-image")
        self.assertEqual(payload["prompt"], "prompt")
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["resolution"], "2k")
        self.assertEqual(payload["response_format"], "b64_json")

    async def test_generate_image_uses_edits_endpoint_with_input_images(self):
        gen = GrokImagineImageGen(api_key="test-key", model="grok-imagine-pro")
        gen._client = types.SimpleNamespace(
            post=AsyncMock(
                return_value=_FakeResponse({"data": [{"b64_json": "edited-b64"}]})
            )
        )
        gen._initialized = True

        result = await gen.generate_image(
            "edit this",
            None,
            None,
            input_images=[{"mime_type": "image/png", "content_b64": "ZmFrZQ=="}],
        )

        self.assertEqual(result, "edited-b64")
        self.assertEqual(gen._client.post.await_args.args[0], "/images/edits")
        payload = gen._client.post.await_args.kwargs["json"]
        self.assertEqual(payload["model"], "grok-imagine-image-pro")
        self.assertEqual(
            payload["image"]["url"],
            "data:image/png;base64,ZmFrZQ==",
        )
        self.assertEqual(payload["image"]["type"], "image_url")

    async def test_generate_image_downloads_url_when_b64_missing(self):
        gen = GrokImagineImageGen(api_key="test-key")
        gen._client = types.SimpleNamespace(
            post=AsyncMock(
                return_value=_FakeResponse(
                    {"data": [{"url": "https://example.com/generated.png"}]}
                )
            )
        )
        gen._initialized = True
        gen._download_image_as_b64 = AsyncMock(return_value="downloaded-b64")

        result = await gen.generate_image("prompt")

        self.assertEqual(result, "downloaded-b64")
        gen._download_image_as_b64.assert_awaited_once_with(
            "https://example.com/generated.png"
        )

    async def test_validate_settings_requires_non_empty_api_key(self):
        with self.assertRaisesRegex(ValueError, "api_key is required"):
            await GrokImagineImageGen.validate_settings(
                {"api_key": "   ", "model": "grok-imagine"}
            )
