"""Генератор изображений через OpenAI Images API (DALL-E / GPT Image)."""

from __future__ import annotations

import asyncio
from typing import Any

from openai import AsyncOpenAI
from pydantic import Field, PrivateAttr

from giga_agent.generators.image.base import BaseImageGenerator, DEFAULT_HEIGHT, DEFAULT_WIDTH
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

# Поддерживаемые размеры для моделей OpenAI Images
SUPPORTED_IMAGE_SIZES: dict[str, list[tuple[int, int]]] = {
    "dall-e-3": [
        (1024, 1024),
        (1792, 1024),
        (1024, 1792),
    ],
    "gpt-image-1": [
        (1024, 1024),
        (1536, 1024),
        (1024, 1536),
    ],
    "dall-e-2": [
        (256, 256),
        (512, 512),
        (1024, 1024),
    ],
}


@ImageGeneratorRegistry.register("openai")
class OpenAIImageGen(BaseImageGenerator):
    """Генерация изображений через OpenAI Images API.

    Возвращает base64-строку изображения (b64_json).

    Settings:
        model: str — Модель (по умолчанию "dall-e-3").
        timeout: float — Таймаут запроса в секундах.
        max_retries: int — Максимальное число ретраев.
    """

    model: str = Field(default="dall-e-3", description="Image model")
    timeout: float = Field(default=60.0, gt=0, description="Request timeout")
    max_retries: int = Field(default=3, ge=1, description="Retry attempts")

    _client: AsyncOpenAI | None = PrivateAttr(default=None)

    async def init(self) -> None:
        connector = self.require_supported_connector()
        api_object = connector.get_api_object()
        self._client = self._resolve_openai_client(api_object)
        if self._client is None:
            raise ValueError(
                "OpenAI client is not configured. "
                "Provide a compatible openai connector."
            )

        await super().init()

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["openai"]

    def _resolve_openai_client(self, api_object: object) -> AsyncOpenAI | None:
        if api_object is None:
            return None

        # Поддержка прямого доступа к _client и root_async_client.
        direct_client = getattr(api_object, "_client", None)
        if isinstance(direct_client, AsyncOpenAI):
            return direct_client

        root_async_client = getattr(api_object, "root_async_client", None)
        if isinstance(root_async_client, AsyncOpenAI):
            return root_async_client

        return None

    async def _generate_image(
        self,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
        **kwargs: Any,
    ) -> str:
        if self._client is None:
            raise RuntimeError("OpenAIImageGen is not initialized. Call init().")

        width = DEFAULT_WIDTH if width is None else width
        height = DEFAULT_HEIGHT if height is None else height
        norm_w, norm_h = self._normalize_size_for_model(self.model, width, height)
        size = f"{norm_w}x{norm_h}"

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    n=1,
                    size=size,
                    response_format="b64_json",
                )
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            images = getattr(response, "data", None) or []
            if not images:
                raise RuntimeError("OpenAI did not return image data")

            first: Any = images[0]
            b64 = getattr(first, "b64_json", None)
            if b64 is None and isinstance(first, dict):
                b64 = first.get("b64_json")
            if not b64:
                raise RuntimeError("OpenAI response does not contain b64_json")
            return b64

    @staticmethod
    def _normalize_size_for_model(
        model: str,
        width: int,
        height: int,
    ) -> tuple[int, int]:
        """Преобразует произвольные width x height к ближайшему поддерживаемому размеру."""
        lower = model.lower()

        supported = None
        for key, sizes in SUPPORTED_IMAGE_SIZES.items():
            if key in lower:
                supported = sizes
                break
        if supported is None and "dalle-2" in lower:
            supported = SUPPORTED_IMAGE_SIZES["dall-e-2"]
        if supported is None:
            supported = SUPPORTED_IMAGE_SIZES["dall-e-3"]

        def orientation(w: int, h: int) -> str:
            if w == h:
                return "square"
            return "landscape" if w > h else "portrait"

        requested_orientation = orientation(width, height)
        same_orientation = [
            (w, h) for (w, h) in supported if orientation(w, h) == requested_orientation
        ]
        candidates = same_orientation if same_orientation else supported

        def distance(w: int, h: int) -> int:
            return abs(w - width) + abs(h - height)

        return min(candidates, key=lambda s: distance(s[0], s[1]))
