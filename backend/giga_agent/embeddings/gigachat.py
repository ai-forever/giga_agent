"""GigaChat embeddings runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_gigachat import GigaChat, GigaChatEmbeddings
from pydantic import Field, PrivateAttr

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.gigachat_token_cache import get_gigachat_access_token_cached
from giga_agent.embeddings.base import (
    AvailableEmbeddingModel,
    BaseEmbeddingRuntime,
    EmbeddingModelFetchError,
)
from giga_agent.embeddings.registry import EmbeddingRegistry


@EmbeddingRegistry.register("gigachat")
class GigaChatEmbeddingRuntime(BaseEmbeddingRuntime):
    timeout: float | None = Field(default=None, gt=0)

    _embeddings_lock: asyncio.Lock | None = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._embeddings_lock = asyncio.Lock()

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

    async def get_embeddings(self) -> GigaChatEmbeddings:
        embeddings = self._embeddings_instance
        if embeddings is not None:
            return embeddings

        if self._embeddings_lock is None:
            self._embeddings_lock = asyncio.Lock()

        async with self._embeddings_lock:
            embeddings = self._embeddings_instance
            if embeddings is None:
                embeddings = await self._create_embeddings()
                self._embeddings_instance = embeddings
            return embeddings

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector: BaseConnector,
    ) -> list[AvailableEmbeddingModel]:
        kwargs = connector.get_connection_kwargs()
        if kwargs is None:
            return []

        try:
            token = await get_gigachat_access_token_cached(connector)
            llm = GigaChat(**kwargs, access_token=token)
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

    async def _create_embeddings(self) -> GigaChatEmbeddings:
        connection_kwargs = self.connector.get_connection_kwargs()
        if connection_kwargs is None:
            raise ValueError("Invalid connection settings for GigaChat embedding runtime")
        token = await get_gigachat_access_token_cached(self.connector)
        settings = self._settings_payload()
        client_kwargs: dict[str, Any] = {
            "model": self.model_id,
            "base_url": connection_kwargs.get("base_url"),
            "credentials": connection_kwargs.get("credentials"),
            "scope": connection_kwargs.get("scope"),
            "user": connection_kwargs.get("user"),
            "password": connection_kwargs.get("password"),
            "verify_ssl_certs": connection_kwargs.get("verify_ssl_certs"),
            "timeout": settings.get("timeout"),
            "access_token": token,
        }

        extra = settings.get("extra")
        if isinstance(extra, dict):
            client_kwargs.update(extra)

        clean_client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        return GigaChatEmbeddings(**clean_client_kwargs)
