import base64
import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.nano_banana.generator import NanoBananaImageGen


class NanoBananaImageGenTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_uses_prompt_only_content(self):
        gen = NanoBananaImageGen(api_key="test-key")
        gen._client = types.SimpleNamespace(
            aio=types.SimpleNamespace(
                models=types.SimpleNamespace(
                    generate_content=AsyncMock(
                        return_value=types.SimpleNamespace(
                            parts=[
                                types.SimpleNamespace(
                                    inline_data=types.SimpleNamespace(data=b"image-bytes")
                                )
                            ]
                        )
                    )
                )
            )
        )
        gen._initialized = True

        with patch(
            "giga_agent.generators.image.nano_banana.generator.genai_types.Part.from_text",
            return_value={"kind": "text", "text": "prompt"},
        ) as mocked_from_text:
            result = await gen.generate_image("prompt", None, None, aspect_ratio="16:9")

        self.assertEqual(result, base64.b64encode(b"image-bytes").decode("ascii"))
        mocked_from_text.assert_called_once_with(text="prompt")
        gen._client.aio.models.generate_content.assert_awaited_once()
        kwargs = gen._client.aio.models.generate_content.await_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-2.5-flash-image")
        self.assertEqual(kwargs["contents"], [{"kind": "text", "text": "prompt"}])
        self.assertEqual(kwargs["config"].response_modalities, ["IMAGE"])
        self.assertEqual(kwargs["config"].image_config.aspect_ratio, "16:9")

    async def test_generate_image_adds_reference_images(self):
        gen = NanoBananaImageGen(api_key="test-key")
        gen._client = types.SimpleNamespace(
            aio=types.SimpleNamespace(
                models=types.SimpleNamespace(
                    generate_content=AsyncMock(
                        return_value=types.SimpleNamespace(
                            candidates=[
                                types.SimpleNamespace(
                                    content=types.SimpleNamespace(
                                        parts=[
                                            types.SimpleNamespace(
                                                inline_data=types.SimpleNamespace(
                                                    data=b"edited-image"
                                                )
                                            )
                                        ]
                                    )
                                )
                            ],
                            parts=[],
                        )
                    )
                )
            )
        )
        gen._initialized = True

        with patch(
            "giga_agent.generators.image.nano_banana.generator.genai_types.Part.from_text",
            return_value={"kind": "text", "text": "edit this"},
        ) as mocked_from_text, patch(
            "giga_agent.generators.image.nano_banana.generator.genai_types.Part.from_bytes",
            return_value={"kind": "bytes", "mime_type": "image/png", "data": b"fake"},
        ) as mocked_from_bytes:
            result = await gen.generate_image(
                "edit this",
                None,
                None,
                input_images=[{"mime_type": "image/png", "content_b64": "ZmFrZQ=="}],
            )

        self.assertEqual(result, base64.b64encode(b"edited-image").decode("ascii"))
        mocked_from_text.assert_called_once_with(text="edit this")
        mocked_from_bytes.assert_called_once_with(data=b"fake", mime_type="image/png")
        kwargs = gen._client.aio.models.generate_content.await_args.kwargs
        self.assertEqual(
            kwargs["contents"],
            [
                {"kind": "text", "text": "edit this"},
                {"kind": "bytes", "mime_type": "image/png", "data": b"fake"},
            ],
        )
        self.assertEqual(kwargs["config"].response_modalities, ["IMAGE"])

    async def test_generate_image_raises_when_image_missing(self):
        gen = NanoBananaImageGen(api_key="test-key")
        gen._client = types.SimpleNamespace(
            aio=types.SimpleNamespace(
                models=types.SimpleNamespace(
                    generate_content=AsyncMock(
                        return_value=types.SimpleNamespace(
                            parts=[types.SimpleNamespace(text="only text", inline_data=None)]
                        )
                    )
                )
            )
        )
        gen._initialized = True

        with self.assertRaisesRegex(RuntimeError, "did not return an image"):
            await gen.generate_image("prompt")

    async def test_validate_settings_requires_non_empty_api_key(self):
        with self.assertRaisesRegex(ValueError, "api_key is required"):
            await NanoBananaImageGen.validate_settings(
                {"api_key": "   ", "model": "gemini-2.5-flash-image"}
            )
