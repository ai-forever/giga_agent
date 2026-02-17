"""Базовый абстрактный класс поискового движка."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, ClassVar, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model


class BaseSearchEngine(BaseModel, abc.ABC):
    """Абстрактный базовый класс для поисковых движков."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    parallel_calls: int = Field(default=1, ge=1)

    _runtime_fields: ClassVar[set[str]] = {
        "parallel_calls",
    }
    _semaphore: asyncio.Semaphore = PrivateAttr()
    _initialized: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: Any) -> None:
        self._semaphore = asyncio.Semaphore(self.parallel_calls)

    async def init(self) -> None:
        """Подготовка runtime-ресурсов движка перед поиском."""
        self._initialized = True

    async def search(self, queries: list[str]) -> list[dict[str, Any]]:
        """Выполнить поиск по списку запросов."""
        if not self._initialized:
            raise RuntimeError(
                f"{self.__class__.__name__}.init() must be called before search()."
            )
        if not queries:
            return []
        async with self._semaphore:
            return await self._search(queries)

    @abc.abstractmethod
    async def _search(self, queries: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @classmethod
    def get_tools(cls) -> list[BaseTool]:
        """Возвращает tools, предоставляемые runtime-поисковиком."""
        from giga_agent.search_engines.tool import search

        return [search]

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        """Сгенерировать Pydantic-модель для валидации settings."""
        fields: dict[str, tuple[Any, Any]] = {}
        for name, field_info in cls.model_fields.items():
            if name in cls._runtime_fields:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        """Валидировать и нормализовать settings."""
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)
