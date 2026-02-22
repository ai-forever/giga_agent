"""OpenAI embeddings runtime."""

from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings
from pydantic import Field

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.embeddings.base import (
    BaseEmbeddingRuntime,
)
from giga_agent.embeddings.registry import EmbeddingRegistry


@EmbeddingRegistry.register("openai")
class OpenAIEmbeddingRuntime(BaseEmbeddingRuntime):
    dimensions: int | None = Field(default=None, ge=1)
    chunk_size: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0)
    request_timeout: float | None = Field(default=None, gt=0)

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["openai"]

    def _embeddings(self) -> OpenAIEmbeddings:
        connection_kwargs = ConnectorRegistry.get_connection_kwargs(
            self.connector.type,
            self.connector.settings or {},
        )
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.id}"
            )
        settings = self._settings_payload()
        client_kwargs: dict[str, Any] = {
            "model": self.model_id,
            "openai_api_key": connection_kwargs.get("api_key"),
            "openai_api_base": connection_kwargs.get("base_url"),
            "dimensions": settings.get("dimensions"),
            "chunk_size": settings.get("chunk_size"),
            "max_retries": settings.get("max_retries"),
            "request_timeout": settings.get("request_timeout"),
        }

        extra = settings.get("extra")
        if isinstance(extra, dict):
            client_kwargs.update(extra)

        clean_client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        return OpenAIEmbeddings(**clean_client_kwargs)
