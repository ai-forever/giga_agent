"""Grok Imagine image generator via xAI Images API."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, ClassVar, Literal

import httpx
from pydantic import Field, PrivateAttr

from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry

GrokImagineModel = Literal["grok-imagine", "grok-imagine-pro"]


@ImageGeneratorRegistry.register("grok_imagine")
class GrokImagineImageGen(BaseImageGenerator):
    """Image generation and editing through xAI Images API."""

    api_key: str = Field(..., description="xAI API key")
    model: GrokImagineModel = Field(
        default="grok-imagine",
        description="Grok Imagine model",
    )

    _client: httpx.AsyncClient | None = PrivateAttr(default=None)

    _base_url: ClassVar[str] = "https://api.x.ai/v1"
    _timeout: ClassVar[float] = 60.0
    _max_retries: ClassVar[int] = 3
    _model_map: ClassVar[dict[str, str]] = {
        "grok-imagine": "grok-imagine-image",
        "grok-imagine-pro": "grok-imagine-image-pro",
    }

    async def init(self) -> None:
        api_key = self.api_key.strip()
        if not api_key:
            raise ValueError("xAI api_key is required and must not be empty")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        await super().init()

    @classmethod
    def get_tools(cls):
        from giga_agent.generators.image.grok.tool import gen_image

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
            raise RuntimeError("GrokImagineImageGen is not initialized. Call init().")

        payload = self._build_payload(prompt=prompt, **kwargs)
        endpoint = (
            "/images/edits" if kwargs.get("input_images") else "/images/generations"
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.post(endpoint, json=payload)
                response.raise_for_status()
                return await self._extract_image_b64(response.json())
            except Exception:
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(2 ** (attempt - 1))

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        validated = await super().validate_settings(settings)
        if not str(validated.get("api_key", "") or "").strip():
            raise ValueError("api_key is required and must not be empty")
        return validated

    def _build_payload(self, *, prompt: str, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._resolve_api_model(self.model),
            "prompt": prompt,
            "response_format": "b64_json",
        }

        aspect_ratio = kwargs.get("aspect_ratio")
        if aspect_ratio is not None:
            payload["aspect_ratio"] = aspect_ratio

        resolution = kwargs.get("resolution")
        if resolution is not None:
            payload["resolution"] = resolution

        input_images = kwargs.get("input_images") or []
        if input_images:
            images_payload = [self._build_image_input(item) for item in input_images]
            if len(images_payload) == 1:
                payload["image"] = images_payload[0]
            else:
                payload["images"] = images_payload

        return payload

    @staticmethod
    def _build_image_input(item: dict[str, str]) -> dict[str, str]:
        mime_type = str(item.get("mime_type") or "").strip()
        content_b64 = str(item.get("content_b64") or "").strip()
        if not mime_type.startswith("image/"):
            raise ValueError(f"Unsupported input image mime type: {mime_type}")
        if not content_b64:
            raise ValueError("Input image content_b64 must not be empty")

        return {
            "type": "image_url",
            "url": f"data:{mime_type};base64,{content_b64}",
        }

    @classmethod
    def _resolve_api_model(cls, model: GrokImagineModel) -> str:
        resolved = cls._model_map.get(model)
        if resolved is None:
            raise ValueError(f"Unsupported Grok Imagine model: {model}")
        return resolved

    async def _extract_image_b64(self, payload: dict[str, Any]) -> str:
        items = payload.get("data")
        if not isinstance(items, list) or not items:
            raise RuntimeError("xAI did not return image data")

        first = items[0]
        if not isinstance(first, dict):
            raise RuntimeError("xAI returned unexpected image payload")

        b64_json = first.get("b64_json")
        if isinstance(b64_json, str) and b64_json:
            return b64_json

        image_url = first.get("url")
        if isinstance(image_url, str) and image_url:
            return await self._download_image_as_b64(image_url)

        raise RuntimeError("xAI response does not contain image data")

    async def _download_image_as_b64(self, image_url: str) -> str:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=self._timeout
        ) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            return base64.b64encode(response.content).decode("ascii")
