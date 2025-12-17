import asyncio

import httpx

from giga_agent.generators.image.image_gen import ImageGen
from giga_agent.settings import settings

# Поддерживаемые размеры для моделей OpenAI Images
# Ключи — подстроки, ожидаемые в имени модели (в нижнем регистре)
SUPPORTED_IMAGE_SIZES: dict[str, list[tuple[int, int]]] = {
    # DALL·E 3
    "dall-e-3": [
        (1024, 1024),
        (1792, 1024),  # landscape
        (1024, 1792),  # portrait
    ],
    # GPT Image 1
    "gpt-image-1": [
        (1024, 1024),
        (1536, 1024),  # landscape
        (1024, 1536),  # portrait
    ],
    # DALL·E 2 (только квадрат)
    "dall-e-2": [
        (256, 256),
        (512, 512),
        (1024, 1024),
    ],
}


class OpenAIImageGen(ImageGen):
    """Генерация изображений через OpenAI Images (DALL·E).

    Возвращает base64-строку изображения (b64_json), совместимую с интерфейсом
    базового класса `ImageGen`.
    """

    def __init__(
        self,
        model: str = "dall-e-3",
        semaphore: asyncio.Semaphore | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = 60.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(model=model, semaphore=semaphore)
        self._api_key: str | None = api_key or settings.providers.openai_api_key
        self._base_url = base_url if base_url else "https://api.openai.com/v1"
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set in the environment and "
                "was not provided to the constructor",
            )
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )
        await super().init()

    async def _generate_image(self, prompt: str, width: int, height: int) -> str:
        if self._client is None or not self._api_key:
            raise RuntimeError("OpenAIImageGen is not initialized. Call init().")

        # Нормализуем произвольные размеры под поддерживаемые моделью
        norm_w, norm_h = self._normalize_size_for_model(self.model, width, height)
        size = f"{norm_w}x{norm_h}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
            # Дополнительно можно управлять качеством/стилем (актуально для dall-e-3):
            # "quality": "high",  # по желанию
            # "style": "vivid",   # или "natural"
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        attempt = 0
        while True:
            attempt += 1
            resp = await self._client.post(
                "/images/generations",
                json=payload,
                headers=headers,
            )

            if resp.is_success:
                data = resp.json()
                # Формат ответа: { "data": [{ "b64_json": "..." }] }
                images = data.get("data", [])
                if not images:
                    raise RuntimeError("OpenAI did not return image data")
                b64 = images[0].get("b64_json")
                if not b64:
                    raise RuntimeError("OpenAI response does not contain b64_json")
                return b64

            # На последней попытке — пробрасываем исключение
            if attempt >= self._max_retries:
                resp.raise_for_status()

            # Простая экспоненциальная пауза на ретраях (в т.ч. для 429/5xx)
            await asyncio.sleep(2 ** (attempt - 1))

    @staticmethod
    def _normalize_size_for_model(
        model: str,
        width: int,
        height: int,
    ) -> tuple[int, int]:
        """Преобразует произвольные width×height к ближайшему поддерживаемому размеру.

        Учитывает ориентацию (горизонтальная/вертикальная/квадрат) и близость размеров.
        Наборы поддерживаемых размеров берутся из константы SUPPORTED_IMAGE_SIZES.
        Если модель не распознана — используется набор как у `dall-e-3`.
        """
        lower = model.lower()

        # Определяем поддерживаемые размеры по ключам из константы
        supported = None
        for key, sizes in SUPPORTED_IMAGE_SIZES.items():
            if key in lower:
                supported = sizes
                break
        # Поддержка возможного варианта написания "dalle-2"
        if supported is None and "dalle-2" in lower:
            supported = SUPPORTED_IMAGE_SIZES["dall-e-2"]
        if supported is None:
            supported = SUPPORTED_IMAGE_SIZES["dall-e-3"]

        def orientation(w: int, h: int) -> str:
            if w == h:
                return "square"
            return "landscape" if w > h else "portrait"

        requested_orientation = orientation(width, height)

        # Сначала ищем среди размеров с той же ориентацией, если такие есть
        same_orientation = [
            (w, h) for (w, h) in supported if orientation(w, h) == requested_orientation
        ]

        candidates = same_orientation if same_orientation else supported

        # Метрика близости — сумма абсолютных отклонений по ширине и высоте
        def distance(w: int, h: int) -> int:
            return abs(w - width) + abs(h - height)

        best = min(candidates, key=lambda s: distance(s[0], s[1]))
        return best
