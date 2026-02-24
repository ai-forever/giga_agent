"""Base runtime class for search engines."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, ClassVar, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, create_model

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry


class BaseSearchEngine(BaseModel, abc.ABC):
    """Abstract base runtime for search engines."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    parallel_calls: int = Field(default=1, ge=1)
    connector: BaseConnector | None = None

    _runtime_fields: ClassVar[set[str]] = {
        "parallel_calls",
        "connector",
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

    def require_supported_connector(self) -> BaseConnector:
        """Validate and return connector runtime for this search engine."""
        supported_types = [item.lower() for item in self.supported_connector_types()]

        if not supported_types:
            raise ValueError(
                f"Search engine '{self.__class__.__name__}' does not support connectors."
            )

        if self.connector is None:
            raise ValueError(
                f"Search engine '{self.__class__.__name__}' requires connector. "
                f"Supported connector types: {supported_types}"
            )

        allowed_classes: tuple[type[BaseConnector], ...] = tuple(
            ConnectorRegistry.get(connector_type) for connector_type in supported_types
        )
        if not isinstance(self.connector, allowed_classes):
            raise ValueError(
                f"Connector runtime '{self.connector.__class__.__name__}' is not "
                f"supported by search engine '{self.__class__.__name__}'. "
                f"Supported connector types: {supported_types}"
            )

        return self.connector

    @classmethod
    def get_tools(cls) -> list[BaseTool]:
        from giga_agent.search_engines.tool import search

        return [search]

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        fields: dict[str, tuple[Any, Any]] = {}
        for name, field_info in cls.model_fields.items():
            if name in cls._runtime_fields:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)
