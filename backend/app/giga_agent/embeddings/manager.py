"""Manager for resolving runtime embeddings clients."""

from __future__ import annotations

import uuid

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.embeddings.registry import EmbeddingRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.embedding import EmbeddingRepository

# Ensure runtimes are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401


class EmbeddingManager:
    @staticmethod
    async def resolve_by_id(
        embedding_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> Embeddings:
        embedding = await EmbeddingRepository.get_cached_or_db(
            embedding_id,
            session=session,
        )
        if embedding is None:
            raise ValueError(f"Embedding with id {embedding_id} not found")
        if not embedding.is_active:
            raise ValueError(f"Embedding with id {embedding_id} is inactive")

        connector = await ConnectorRepository.get_cached_or_db(
            embedding.connector_id,
            session=session,
        )
        if connector is None:
            raise ValueError(f"Connector for embedding {embedding_id} not found")
        if not connector.is_active:
            raise ValueError(f"Connector {connector.id} is inactive")

        runtime_cls = EmbeddingRegistry.get(embedding.type)
        if not runtime_cls.is_connector_supported(connector.type):
            raise ValueError(
                f"Embedding type '{embedding.type}' is not compatible with connector type "
                f"'{connector.type}'"
            )

        kwargs = ConnectorRegistry.get_connection_kwargs(
            connector.type,
            connector.settings or {},
        )
        if kwargs is None:
            raise ValueError(f"Invalid connection settings for connector {connector.id}")

        return runtime_cls.build_embeddings_from_kwargs(
            model_id=embedding.model_id,
            connection_kwargs=kwargs,
            embedding_settings=embedding.settings or {},
        )
