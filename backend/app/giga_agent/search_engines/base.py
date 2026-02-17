"""Base runtime class for search engines."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, ClassVar, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model


class BaseSearchEngine(BaseModel, abc.ABC):
    """Abstract base runtime for search engines."""

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
        self._initialized = True

    async def search(self, queries: list[str]) -> list[dict[str, Any]]:
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
    def supported_connector_types(cls) -> list[str]:
        """Connector types accepted by this search runtime. Empty means no connector."""
        return []

    @classmethod
    def connector_settings_fields(cls) -> set[str]:
        """Runtime fields that are sourced from connector settings, not engine settings."""
        return set()

    @classmethod
    def get_tools(cls) -> list[BaseTool]:
        from giga_agent.search_engines.tool import search

        return [search]

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        fields: dict[str, tuple[Any, Any]] = {}
        excluded = cls._runtime_fields | cls.connector_settings_fields()
        for name, field_info in cls.model_fields.items():
            if name in excluded:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)
