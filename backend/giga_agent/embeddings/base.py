"""Base runtime classes for embeddings providers."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, ClassVar, Type

from langchain_core.embeddings import Embeddings
from langchain_core.rate_limiters import BaseRateLimiter
from pydantic import BaseModel, ConfigDict, PrivateAttr, create_model

from giga_agent.connectors.base import BaseConnector


class _RateLimitedEmbeddings(Embeddings):
    """Wraps an Embeddings client and acquires a rate-limit token per async call.

    Only the async methods are gated (the agent/RAG paths use ``aembed_*``); the sync
    methods delegate unchanged.
    """

    def __init__(self, inner: Embeddings, limiter: BaseRateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        await self._limiter.aacquire(blocking=True)
        return await self._inner.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        await self._limiter.aacquire(blocking=True)
        return await self._inner.aembed_query(text)


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

    _embeddings_instance: Embeddings | None = PrivateAttr(default=None)
    _rate_limiter: BaseRateLimiter | None = PrivateAttr(default=None)

    def attach_rate_limiter(self, limiter: BaseRateLimiter | None) -> None:
        """Attach a rate limiter applied on every embeddings invocation."""
        self._rate_limiter = limiter

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

    async def get_embeddings(self) -> Embeddings:
        embeddings = self._embeddings_instance
        if embeddings is not None:
            return embeddings
        embeddings = await self._create_embeddings()
        if self._rate_limiter is not None:
            embeddings = _RateLimitedEmbeddings(embeddings, self._rate_limiter)
        self._embeddings_instance = embeddings
        return embeddings

    @abc.abstractmethod
    async def _create_embeddings(self) -> Embeddings:
        raise NotImplementedError

    async def check_connection(self) -> bool:
        embeddings = await self.get_embeddings()
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
