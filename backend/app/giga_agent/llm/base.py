"""Base runtime classes for LLM providers."""

from __future__ import annotations

import abc
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

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


class BaseLLM(BaseModel, abc.ABC):
    """LLM runtime contract used by routes and repositories."""

    @classmethod
    @abc.abstractmethod
    def supported_connector_types(cls) -> list[str]:
        raise NotImplementedError

    @classmethod
    def is_connector_supported(cls, connector_type: str) -> bool:
        return (connector_type or "").lower() in {
            t.lower() for t in cls.supported_connector_types()
        }

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

    @classmethod
    def build_chat_model(
        cls,
        *,
        model_id: str,
        connector_type: str,
        connector_settings: dict[str, Any],
        llm_settings: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        kwargs = cls._get_connection_kwargs(
            connector_type=connector_type,
            connector_settings=connector_settings,
        )
        if kwargs is None:
            raise ValueError(
                f"Invalid connector settings for connector type '{connector_type}'"
            )

        return cls.build_chat_model_from_kwargs(
            model_id=model_id,
            connection_kwargs=kwargs,
            llm_settings=llm_settings,
        )

    @classmethod
    @abc.abstractmethod
    def build_chat_model_from_kwargs(
        cls,
        *,
        model_id: str,
        connection_kwargs: dict[str, Any],
        llm_settings: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        raise NotImplementedError
