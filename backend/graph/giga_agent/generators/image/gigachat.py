import asyncio
import base64

import httpx

from giga_agent.generators.image.image_gen import ImageGen
from giga_agent.utils.llm import load_gigachat


class CensorException(Exception):
    """Запрос отклонён цензурой (HTTP 451)."""


class GigaChatImageGen(ImageGen):
    """Генерация через GigaChat Devices API."""

    def __init__(
        self,
        model: str,
        semaphore: asyncio.Semaphore | None = None,
        *,
        token: str | None = None,
        timeout: float | None = 60.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(model=model, semaphore=semaphore)
        self._token: str | None = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = None

    async def init(self) -> None:
        llm = load_gigachat()

        self._client = httpx.AsyncClient(
            verify=False,
            timeout=self._timeout,
            base_url=llm._client._client.base_url,
        )
        if self._token is None:
            self._token = (await llm._client.aget_token()).access_token
        await super().init()

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

            if resp.status_code in [451]:
                raise CensorException("Server returned HTTP 451 — access restricted.")

            if resp.is_success:
                return base64.b64encode(resp.content).decode("ascii")

            if attempt >= self._max_retries:
                resp.raise_for_status()
            else:
                await asyncio.sleep(2 ** (attempt - 1))
