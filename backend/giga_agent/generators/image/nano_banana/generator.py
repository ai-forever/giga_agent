"""Nano Banana image generator via Google GenAI SDK."""

from __future__ import annotations

import base64
from typing import Any, Iterable, Literal

from google import genai
from google.genai import types as genai_types
from pydantic import Field, PrivateAttr

from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry

NanoBananaAspectRatio = Literal["1:1", "3:4", "4:3", "9:16", "16:9"]


@ImageGeneratorRegistry.register("nano_banana")
class NanoBananaImageGen(BaseImageGenerator):
    """Image generation and reference-based generation through Gemini image models."""

    api_key: str = Field(..., description="Google Gemini API key")
    model: str = Field(
        default="gemini-2.5-flash-image",
        description="Gemini image generation model",
    )

    _client: genai.Client | None = PrivateAttr(default=None)

    async def init(self) -> None:
        api_key = self.api_key.strip()
        if not api_key:
            raise ValueError("api_key is required and must not be empty")

        self._client = genai.Client(api_key=api_key)
        await super().init()

    @classmethod
    def get_tools(cls):
        from giga_agent.generators.image.nano_banana.tool import gen_image

        return [gen_image]

    async def _generate_image(
        self,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
        **kwargs: Any,
    ) -> str:
        _ = width, height
        if self._client is None:
            raise RuntimeError("NanoBananaImageGen is not initialized. Call init().")

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=self._build_contents(prompt=prompt, input_images=kwargs.get("input_images")),
            config=self._build_config(aspect_ratio=kwargs.get("aspect_ratio")),
        )
        return self._extract_image_b64(response)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        validated = await super().validate_settings(settings)
        if not str(validated.get("api_key", "") or "").strip():
            raise ValueError("api_key is required and must not be empty")
        return validated

    def _build_contents(
        self,
        *,
        prompt: str,
        input_images: list[dict[str, str]] | None,
    ) -> list[Any]:
        contents: list[genai_types.Part] = [prompt]

        for item in input_images or []:
            mime_type = str(item.get("mime_type") or "").strip()
            content_b64 = str(item.get("content_b64") or "").strip()
            if not mime_type.startswith("image/"):
                raise ValueError(f"Unsupported input image mime type: {mime_type}")
            if not content_b64:
                raise ValueError("Input image content_b64 must not be empty")

            contents.append(
                genai_types.Part.from_bytes(
                    data=base64.b64decode(content_b64),
                    mime_type=mime_type,
                )
            )

        return contents

    @staticmethod
    def _build_config(
        *,
        aspect_ratio: NanoBananaAspectRatio | None,
    ) -> genai_types.GenerateContentConfig:
        image_config = (
            genai_types.ImageConfig(aspect_ratio=aspect_ratio)
            if aspect_ratio is not None
            else None
        )
        return genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=image_config,
        )

    async def check_connection(self) -> bool:
        await self.init()
        await self.generate_image("generate image of cat", 256, 256)
        return True

    @staticmethod
    def _iter_response_parts(
        response: genai_types.GenerateContentResponse,
    ) -> Iterable[genai_types.Part]:
        if response.parts:
            return response.parts

        candidates = response.candidates or []
        if candidates and candidates[0].content and candidates[0].content.parts:
            return candidates[0].content.parts

        return []

    def _extract_image_b64(self, response: genai_types.GenerateContentResponse) -> str:
        for part in self._iter_response_parts(response):
            if part.inline_data is not None:
                return base64.b64encode(part.inline_data.data).decode("ascii")

        raise RuntimeError("Gemini did not return an image for this prompt.")
