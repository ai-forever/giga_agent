"""Базовый абстрактный класс генератора изображений."""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, ClassVar, Type

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model

logger = logging.getLogger(__name__)

# Дефолтные размеры изображения
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024


class BaseImageGenerator(BaseModel, abc.ABC):
    """Абстрактный базовый класс для генераторов изображений.

    Контракт:
      - Подклассы реализуют `_generate_image(prompt, width, height) -> str` (base64).
      - `generate_image` — обёртка с семафором.
      - `settings_schema()` / `validate_settings()` — для валидации провайдерских настроек.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    parallel_calls: int = Field(default=1, ge=1)
    llm: BaseChatModel | None = None

    # Поля, управляемые системой (не хранятся в settings JSON).
    _runtime_fields: ClassVar[set[str]] = {
        "parallel_calls",
        "llm",
    }
    _semaphore: asyncio.Semaphore = PrivateAttr()
    _initialized: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        self._semaphore = asyncio.Semaphore(self.parallel_calls)

    @abc.abstractmethod
    async def init(self) -> None:
        """Подготовка ресурсов перед генерацией (токены, клиенты и т.д.)."""
        self._initialized = True

    async def generate_image(
        self,
        prompt: str,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> str:
        """Генерирует изображение с ограничением семафором.

        Returns:
            base64-строка изображения.
        """
        if not self._initialized:
            raise RuntimeError(
                f"{self.__class__.__name__}.init() must be called before generate_image()."
            )
        async with self._semaphore:
            return await self._generate_image(prompt, width, height)

    @abc.abstractmethod
    async def _generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
    ) -> str:
        """Реализация генерации. Возвращает base64-строку."""
        raise NotImplementedError

    @classmethod
    def supported_llm_provider_types(cls) -> list[str]:
        """
        Возвращает список поддерживаемых типов llm_provider для генератора.

        Пустой список означает, что к генератору нельзя подключать llm_provider.
        """
        return []

    @classmethod
    def get_tools(cls) -> list[BaseTool]:
        """Возвращает tools, предоставляемые данным runtime-генератором."""
        from giga_agent.generators.image.tool import gen_image

        return [gen_image]

    # ============ Settings validation ============

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        """
        Динамически генерирует Pydantic-модель для валидации settings.

        Берёт все публичные поля runtime-класса и исключает _runtime_fields
        (поля, которые прокидываются системой, а не хранятся в settings JSON).
        """
        fields: dict[str, tuple[Any, Any]] = {}
        for name, field_info in cls.model_fields.items():
            if name in cls._runtime_fields:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        """
        Валидировать и нормализовать settings.

        Базовая реализация проверяет только схему.
        Подклассы могут расширить для проверки реального подключения.
        """
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)
