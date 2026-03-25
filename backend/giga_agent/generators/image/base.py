"""Базовый абстрактный класс генератора изображений."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, ClassVar, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

# Дефолтные размеры изображения
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024


class BaseImageGenerator(BaseModel, abc.ABC):
    """Абстрактный базовый класс для генераторов изображений.

    Контракт:
      - Подклассы реализуют `_generate_image(prompt, width, height, **kwargs) -> str` (base64).
      - `width` и `height` optional: провайдер сам нормализует `None`.
      - `generate_image` — обёртка с семафором.
      - `settings_schema()` / `validate_settings()` — для валидации провайдерских настроек.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    parallel_calls: int = Field(default=1, ge=1)
    connector: BaseConnector | None = None

    # Поля, управляемые системой (не хранятся в settings JSON).
    _runtime_fields: ClassVar[set[str]] = {
        "parallel_calls",
        "connector",
    }
    _semaphore: asyncio.Semaphore = PrivateAttr()
    _initialized: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        self._semaphore = asyncio.Semaphore(self.parallel_calls)

    @abc.abstractmethod
    async def init(self) -> None:
        """Подготовка ресурсов перед генерацией (токены, клиенты и т.д.)."""
        self._initialized = True

    async def cleanup(self) -> None:
        """Освобождение ресурсов (HTTP-клиенты и т.д.).

        Подклассы с долгоживущими ресурсами должны переопределить этот метод.
        """

    async def check_connection(self) -> bool:
        await self.init()
        try:
            await self.generate_image("ping", 256, 256)
            return True
        finally:
            await self.cleanup()

    async def generate_image(
        self,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
        **kwargs: Any,
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
            return await self._generate_image(prompt, width, height, **kwargs)

    @abc.abstractmethod
    async def _generate_image(
        self,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Реализация генерации. Возвращает base64-строку."""
        raise NotImplementedError

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        """
        Возвращает список поддерживаемых типов connector для генератора.

        Пустой список означает, что к генератору нельзя подключать connector.
        """
        return []

    @classmethod
    def get_tools(cls) -> list[BaseTool]:
        """Возвращает tools, предоставляемые данным runtime-генератором."""
        from giga_agent.generators.image.tool import gen_image

        return [gen_image]

    def require_supported_connector(self) -> BaseConnector:
        """
        Проверить и вернуть connector для генератора.

        Базовая проверка:
        - если генератор требует connector, он должен быть передан;
        - runtime connector должен соответствовать одному из supported_connector_types().
        """
        supported_types = [item.lower() for item in self.supported_connector_types()]

        if not supported_types:
            raise ValueError(
                f"Image generator '{self.__class__.__name__}' does not support connectors."
            )

        if self.connector is None:
            raise ValueError(
                f"Image generator '{self.__class__.__name__}' requires connector. "
                f"Supported connector types: {supported_types}"
            )

        allowed_classes: tuple[type[BaseConnector], ...] = tuple(
            ConnectorRegistry.get(connector_type) for connector_type in supported_types
        )
        if not isinstance(self.connector, allowed_classes):
            raise ValueError(
                f"Connector runtime '{self.connector.__class__.__name__}' is not supported by "
                f"image generator '{self.__class__.__name__}'. Supported connector types: "
                f"{supported_types}"
            )

        return self.connector

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
