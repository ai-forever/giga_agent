"""Генератор изображений через GigaChat Devices API."""

from __future__ import annotations

import asyncio
import base64

import httpx
from pydantic import Field, PrivateAttr

from giga_agent.connectors.gigachat_token_cache import (
    get_gigachat_access_token_cached,
    get_gigachat_access_token_uncached,
    should_skip_gigachat_token_cache,
)
from giga_agent.generators.image.base import (
    BaseImageGenerator,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
)
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
    max_retries: int = Field(default=3, ge=1, le=6, description="Retry attempts")

    _token: str | None = PrivateAttr(default=None)
    _client: httpx.AsyncClient | None = PrivateAttr(default=None)

    async def init(self) -> None:
        connector = self.require_supported_connector()
        api_object = connector.get_api_object()
        gigachat_client = self._resolve_gigachat_client(api_object)

        if gigachat_client is None:
            raise ValueError(
                "GigaChat client is not configured. "
                "Provide a compatible gigachat connector."
            )

        self._token = await self._get_access_token(
            connector,
            api_object=api_object,
        )

        base_url = getattr(getattr(gigachat_client, "_client", None), "base_url", None)
        if base_url is None:
            raise ValueError(
                "Could not resolve GigaChat base_url from connector client"
            )

        self._client = httpx.AsyncClient(
            verify=False,
            timeout=self.timeout,
            base_url=str(base_url),
        )
        await super().init()

    async def cleanup(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

    def _resolve_gigachat_client(self, api_object: object):
        if api_object is None:
            return None

        client = getattr(api_object, "_client", None)
        if client is None:
            return None
        if not hasattr(client, "aget_token"):
            return None
        return client

    async def _get_access_token(
        self,
        connector,
        *,
        api_object: object | None = None,
        force_refresh: bool = False,
    ) -> str:
        if should_skip_gigachat_token_cache():
            return await get_gigachat_access_token_uncached(
                connector,
                api_object=api_object,
            )
        return await get_gigachat_access_token_cached(
            connector,
            api_object=api_object,
            force_refresh=force_refresh,
        )

    async def _generate_image(
        self,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
        **kwargs,
    ) -> str:
        if self._client is None or self._token is None:
            raise RuntimeError("GigaChatImageGen is not initialized. Call init().")

        width = DEFAULT_WIDTH if width is None else width
        height = DEFAULT_HEIGHT if height is None else height
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
        refreshed = False
        while True:
            attempt += 1
            resp = await self._client.post(
                "/image/generate",
                json=payload,
                headers=headers,
            )

            if resp.status_code in {401, 403} and not refreshed:
                refreshed = True
                connector = self.require_supported_connector()
                self._token = await self._get_access_token(
                    connector,
                    force_refresh=True,
                )
                headers["Authorization"] = f"Bearer {self._token}"
                continue

            if resp.status_code == 451:
                raise CensorException(
                    "GigaChat image generation request rejected by censor (HTTP 451)."
                )

            if resp.is_success:
                return base64.b64encode(resp.content).decode("ascii")

            if attempt >= self.max_retries:
                resp.raise_for_status()

            await asyncio.sleep(2 ** (attempt - 1))
