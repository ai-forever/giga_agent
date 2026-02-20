"""Генератор изображений через GigaChat Devices API."""

from __future__ import annotations

import asyncio
import base64

import httpx
from pydantic import Field, PrivateAttr

from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class CensorException(Exception):
    """Запрос отклонён цензурой (HTTP 451)."""


@ImageGeneratorRegistry.register("gigachat")
class GigaChatImageGen(BaseImageGenerator):
    """Генерация изображений через GigaChat Devices API.

    Settings:
        model: str — Модель генерации (по умолчанию "kandinsky-4.1").
        timeout: float — Таймаут запроса.
        max_retries: int — Максимальное число ретраев.
    """

    model: str = Field(default="kandinsky-4.1", description="Image model")
    timeout: float = Field(default=60.0, gt=0, description="Request timeout")
    max_retries: int = Field(default=3, ge=1, description="Retry attempts")

    _token: str | None = PrivateAttr(default=None)
    _client: httpx.AsyncClient | None = PrivateAttr(default=None)

    async def init(self) -> None:
        gigachat_client = self._resolve_gigachat_client_from_llm()

        if gigachat_client is None:
            raise ValueError(
                "GigaChat client is not configured. "
                "Provide a compatible llm client from a GigaChat provider."
            )

        token_data = await gigachat_client.aget_token()
        self._token = token_data.access_token

        base_url = getattr(getattr(gigachat_client, "_client", None), "base_url", None)
        if base_url is None:
            raise ValueError("Could not resolve GigaChat base_url from llm client")

        self._client = httpx.AsyncClient(
            verify=False,
            timeout=self.timeout,
            base_url=str(base_url),
        )
        await super().init()

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

    def _resolve_gigachat_client_from_llm(self):
        if self.llm is None:
            return None

        client = getattr(self.llm, "_client", None)
        if client is None:
            return None
        if not hasattr(client, "aget_token"):
            return None
        return client

    async def _generate_image(self, prompt: str, width: int, height: int) -> str:
        if self._client is None or self._token is None:
            raise RuntimeError("GigaChatImageGen is not initialized. Call init().")

        payload = {
            "mode": f"{self.model}:image",
            "query": prompt,
            "model_params": {
                "width": width,
                "height": height,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

        attempt = 0
        while True:
            attempt += 1
            resp = await self._client.post(
                "/image/generate",
                json=payload,
                headers=headers,
            )

            if resp.status_code == 451:
                raise CensorException(
                    "GigaChat image generation request rejected by censor (HTTP 451)."
                )

            if resp.is_success:
                return base64.b64encode(resp.content).decode("ascii")

            if attempt >= self.max_retries:
                resp.raise_for_status()

            await asyncio.sleep(2 ** (attempt - 1))
