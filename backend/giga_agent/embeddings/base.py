"""Base runtime classes for embeddings providers."""

from __future__ import annotations

import abc
import asyncio
from functools import cached_property
from typing import Any, ClassVar, Type

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, ConfigDict, create_model

from giga_agent.connectors.base import BaseConnector


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
    connector: BaseConnector
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
        return self._embeddings()

    @abc.abstractmethod
    def _embeddings(self) -> Embeddings:
        raise NotImplementedError

    async def check_connection(self) -> bool:
        embeddings = self.embeddings
        if hasattr(embeddings, "aembed_query"):
            await embeddings.aembed_query("ping")
        else:
            await asyncio.to_thread(embeddings.embed_query, "ping")
        return True

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector: BaseConnector,
    ) -> list[AvailableEmbeddingModel]:
        _ = connector
        return []
