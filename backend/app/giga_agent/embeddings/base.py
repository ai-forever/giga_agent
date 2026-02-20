"""Base runtime classes for embeddings providers."""

from __future__ import annotations

import abc
from functools import cached_property
from typing import Any, ClassVar, Type

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, ConfigDict, create_model

from giga_agent.connectors.registry import ConnectorRegistry


class EmbeddingModelFetchError(Exception):
    def __init__(self, embedding_type: str, detail: str):
        self.embedding_type = embedding_type
        self.detail = detail
        super().__init__(
            f"Error fetching embedding models from {embedding_type}: {detail}"
        )


class AvailableEmbeddingModel(BaseModel):
    id: str
    name: str | None = None
    created: int | None = None
    owned_by: str | None = None


class BaseEmbeddingRuntime(BaseModel, abc.ABC):
    """Embeddings runtime contract used by routes and RAG.

    Две роли:
    - **schema/validation**: `settings_schema()` / `validate_settings()` работают с полями
      runtime-класса (подкласса) и исключают системные поля (`_runtime_fields`) и скрытые поля
      (`hidden_settings_fields`).
    - **runtime**: инстанс хранит `connector`, `model_id`, `vector_size` и лениво строит
      langchain embeddings клиент через `embeddings`.
    """

    model_config = ConfigDict(extra="forbid")

    # System/runtime-managed fields (НЕ часть embedding.settings)
    # Важно: не типизируем на ConnectorResponse, чтобы не создавать циклические импорты
    # через `giga_agent.models.__init__`. Достаточно контракта: `.type`, `.settings`, `.id`.
    connector: Any
    model_id: str
    vector_size: int

    _runtime_fields: ClassVar[set[str]] = {
        "connector",
        "model_id",
        "vector_size",
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
        # Для runtime (build client) нужны ВСЕ embedding settings, включая скрытые.
        return self.model_dump(exclude=self._runtime_fields, exclude_none=True)

    @cached_property
    def embeddings(self) -> Embeddings:
        connection_kwargs = ConnectorRegistry.get_connection_kwargs(
            self.connector.type,
            self.connector.settings or {},
        )
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.id}"
            )

        client = self.__class__.build_embeddings_from_kwargs(
            model_id=self.model_id,
            connection_kwargs=connection_kwargs,
            embedding_settings=self._settings_payload(),
        )
        # Some downstream code (and tests) rely on `embeddings.vector_size` being present.
        # Not every langchain embeddings client exposes it, so we set it best-effort.
        try:
            setattr(client, "vector_size", self.vector_size)
        except Exception:
            pass
        return client

    @classmethod
    def _get_connection_kwargs(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not cls.is_connector_supported(connector_type):
            raise ValueError(
                f"Connector type '{connector_type}' is not supported by embeddings runtime "
                f"'{cls.__name__}'. Supported: {cls.supported_connector_types()}"
            )
        return ConnectorRegistry.get_connection_kwargs(
            connector_type, connector_settings
        )

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> list[AvailableEmbeddingModel]:
        _ = connector_type, connector_settings
        return []

    @classmethod
    def build_embeddings(
        cls,
        *,
        model_id: str,
        connector_type: str,
        connector_settings: dict[str, Any],
        embedding_settings: dict[str, Any] | None = None,
    ) -> Embeddings:
        kwargs = cls._get_connection_kwargs(
            connector_type=connector_type,
            connector_settings=connector_settings,
        )
        if kwargs is None:
            raise ValueError(
                f"Invalid connector settings for connector type '{connector_type}'"
            )

        return cls.build_embeddings_from_kwargs(
            model_id=model_id,
            connection_kwargs=kwargs,
            embedding_settings=embedding_settings,
        )

    @classmethod
    @abc.abstractmethod
    def build_embeddings_from_kwargs(
        cls,
        *,
        model_id: str,
        connection_kwargs: dict[str, Any],
        embedding_settings: dict[str, Any] | None = None,
    ) -> Embeddings:
        raise NotImplementedError
