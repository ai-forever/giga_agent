"""Base runtime classes for LLM providers."""

from __future__ import annotations

import abc
from functools import cached_property
from typing import Any, ClassVar, Type

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, create_model

from giga_agent.connectors.registry import ConnectorRegistry


class ModelFetchError(Exception):
    def __init__(self, llm_type: str, detail: str):
        self.llm_type = llm_type
        self.detail = detail
        super().__init__(f"Error fetching models from {llm_type}: {detail}")


class AvailableModel(BaseModel):
    id: str
    name: str | None = None
    created: int | None = None
    owned_by: str | None = None


class BaseLLMRuntime(BaseModel, abc.ABC):
    """LLM runtime contract used by routes and repositories."""

    model_config = ConfigDict(extra="allow")

    connector: Any
    model_id: str

    _runtime_fields: ClassVar[set[str]] = {
        "connector",
        "model_id",
    }

    @classmethod
    @abc.abstractmethod
    def supported_connector_types(cls) -> list[str]:
        raise NotImplementedError

    @classmethod
    def hidden_settings_fields(cls) -> set[str]:
        """Settings fields that must NOT be exposed on the frontend."""
        return set()

    @classmethod
    def is_connector_supported(cls, connector_type: str) -> bool:
        return (connector_type or "").lower() in {
            t.lower() for t in cls.supported_connector_types()
        }

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        fields: dict[str, tuple[Any, Any]] = {}
        excluded = cls._runtime_fields | cls.hidden_settings_fields()

        for name, field_info in cls.model_fields.items():
            if name in excluded:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)

    def _settings_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude=self._runtime_fields, exclude_none=True)

    @cached_property
    def llm(self) -> BaseChatModel:
        return self._llm()

    @abc.abstractmethod
    def _llm(self) -> BaseChatModel:
        raise NotImplementedError

    async def check_connection(self) -> None:
        await self.llm.ainvoke("ping")

    @classmethod
    def _get_connection_kwargs(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not cls.is_connector_supported(connector_type):
            raise ValueError(
                f"Connector type '{connector_type}' is not supported by LLM '{cls.__name__}'. "
                f"Supported: {cls.supported_connector_types()}"
            )
        return ConnectorRegistry.get_connection_kwargs(connector_type, connector_settings)

    @classmethod
    @abc.abstractmethod
    async def fetch_available_models(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> list[AvailableModel]:
        raise NotImplementedError
