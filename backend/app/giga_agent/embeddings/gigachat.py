"""GigaChat embeddings runtime."""

from __future__ import annotations

from typing import Any

from langchain_gigachat import GigaChat, GigaChatEmbeddings
from pydantic import Field

from giga_agent.embeddings.base import (
    AvailableEmbeddingModel,
    BaseEmbeddingRuntime,
    EmbeddingModelFetchError,
)
from giga_agent.embeddings.registry import EmbeddingRegistry


@EmbeddingRegistry.register("gigachat")
class GigaChatEmbeddingRuntime(BaseEmbeddingRuntime):
    timeout: float | None = Field(default=None, gt=0)

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> list[AvailableEmbeddingModel]:
        kwargs = cls._get_connection_kwargs(
            connector_type=connector_type,
            connector_settings=connector_settings,
        )
        if kwargs is None:
            return []

        try:
            llm = GigaChat(**kwargs)
            models = [
                AvailableEmbeddingModel(
                    id=model.id_,
                    name=model.id_,
                    owned_by=model.owned_by,
                )
                for model in (await llm.aget_models()).data
            ]
            models.sort(key=lambda item: item.id)
            return models
        except Exception as e:
            raise EmbeddingModelFetchError("gigachat", str(e)) from e

    @classmethod
    def build_embeddings_from_kwargs(
        cls,
        *,
        model_id: str,
        connection_kwargs: dict[str, Any],
        embedding_settings: dict[str, Any] | None = None,
    ) -> GigaChatEmbeddings:
        settings = embedding_settings or {}
        client_kwargs: dict[str, Any] = {
            "model": model_id,
            "base_url": connection_kwargs.get("base_url"),
            "credentials": connection_kwargs.get("credentials"),
            "scope": connection_kwargs.get("scope"),
            "user": connection_kwargs.get("user"),
            "password": connection_kwargs.get("password"),
            "verify_ssl_certs": connection_kwargs.get("verify_ssl_certs"),
            "timeout": settings.get("timeout"),
        }

        extra = settings.get("extra")
        if isinstance(extra, dict):
            client_kwargs.update(extra)

        clean_client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        return GigaChatEmbeddings(**clean_client_kwargs)
