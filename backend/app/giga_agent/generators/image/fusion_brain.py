"""Генератор изображений через FusionBrain (Kandinsky) API."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from pydantic import Field, PrivateAttr

from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry

logger = logging.getLogger(__name__)


class _AsyncKandinskyClient:
    """Внутренний асинхронный клиент для Kandinsky / FusionBrain API."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self.base_url = "https://api-key.fusionbrain.ai/"
        self.auth_headers = {
            "X-Key": f"Key {api_key}",
            "X-Secret": f"Secret {secret_key}",
        }
        self._pipeline_id: str | None = None
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.auth_headers,
        )

    async def get_pipeline(self) -> str:
        if self._pipeline_id:
            return self._pipeline_id
        resp = await self.client.get("key/api/v1/pipelines")
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise RuntimeError("FusionBrain returned empty pipelines list")
        self._pipeline_id = data[0]["id"]
        return self._pipeline_id

    async def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        style: str = "DEFAULT",
        negative_prompt: str = "",
    ) -> str:
        pipeline_id = await self.get_pipeline()
        params = {
            "type": "GENERATE",
            "style": style,
            "width": width,
            "height": height,
            "numImages": 1,
            "generateParams": {"query": prompt},
        }
        if negative_prompt:
            params["negativePromptDecoder"] = negative_prompt

        files = {
            "pipeline_id": (None, pipeline_id),
            "params": (None, json.dumps(params), "application/json"),
        }
        resp = await self.client.post("key/api/v1/pipeline/run", files=files)
        resp.raise_for_status()
        return resp.json()["uuid"]

    async def check_generation(
        self,
        request_id: str,
        attempts: int = 20,
        delay: float = 5.0,
    ) -> list[str]:
        for _ in range(attempts):
            resp = await self.client.get(f"key/api/v1/pipeline/status/{request_id}")
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status == "DONE":
                return data["result"]["files"]
            if status == "FAIL":
                raise RuntimeError(
                    f"FusionBrain generation failed: "
                    f"{data.get('errorDescription', 'Unknown error')}"
                )
            await asyncio.sleep(delay)

        raise TimeoutError(
            f"FusionBrain generation timed out after {attempts} attempts"
        )

    async def generate_and_get_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        style: str = "DEFAULT",
        negative_prompt: str = "",
    ) -> list[str]:
        request_id = await self.generate(prompt, width, height, style, negative_prompt)
        return await self.check_generation(request_id)


@ImageGeneratorRegistry.register("fusion_brain")
class FusionBrainImageGen(BaseImageGenerator):
    """Генерация изображений через FusionBrain (Kandinsky API).

    Settings:
        api_key: str — API ключ FusionBrain (обязательный).
        secret_key: str — Secret ключ FusionBrain (обязательный).
    """

    api_key: str = Field(..., description="FusionBrain API key")
    secret_key: str = Field(..., description="FusionBrain secret key")

    _api: _AsyncKandinskyClient | None = PrivateAttr(default=None)

    async def init(self) -> None:
        api_key = self.api_key.strip()
        secret_key = self.secret_key.strip()
        if not api_key or not secret_key:
            raise ValueError(
                "FusionBrain api_key and secret_key are required. "
                "Provide them in image generator settings."
            )
        self._api = _AsyncKandinskyClient(api_key=api_key, secret_key=secret_key)
        await super().init()

    async def _generate_image(self, prompt: str, width: int, height: int) -> str:
        if self._api is None:
            raise RuntimeError("FusionBrainImageGen is not initialized. Call init().")

        files = await self._api.generate_and_get_image(
            prompt,
            width=width,
            height=height,
        )
        if not files:
            raise RuntimeError("FusionBrain returned no image data")
        return files[0]

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        """Валидация settings с проверкой ключей."""
        validated = await super().validate_settings(settings)
        for key in ("api_key", "secret_key"):
            val = str(validated.get(key, "") or "").strip()
            if not val:
                raise ValueError(f"{key} is required and must not be empty")
        return validated
