from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels


def _default_local_storage_path() -> Path:
    from giga_agent.core.paths import ensure_giga_agent_dir

    return ensure_giga_agent_dir() / "qdrant"


def get_qdrant_client() -> AsyncQdrantClient:
    """
    Qdrant client factory.

    - If QDRANT_URL is set → connect to remote Qdrant.
    - Otherwise → use local persistent mode in <repo_root>/.giga_agent/qdrant
    """
    url = (os.getenv("QDRANT_URL") or "").strip()
    api_key = (os.getenv("QDRANT_API_KEY") or "").strip() or None

    if url:
        return AsyncQdrantClient(url=url, api_key=api_key)

    path = _default_local_storage_path()
    path.mkdir(parents=True, exist_ok=True)
    return AsyncQdrantClient(path=str(path))


def qdrant_collection_name_for_embedding(embedding_id: uuid.UUID) -> str:
    # Qdrant collection names are best kept simple ASCII.
    return f"rag_chunks__{embedding_id.hex}"


async def ensure_qdrant_collection(
    *,
    client: AsyncQdrantClient,
    collection_name: str,
    vector_size: int,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
    on_disk: bool = False,
) -> None:
    """
    Ensure a Qdrant collection exists with a given vector size.
    """
    if vector_size <= 0:
        raise ValueError("vector_size must be > 0")

    try:
        info = await client.get_collection(collection_name=collection_name)
        existing = getattr(info.config.params, "vectors", None)
        # If already exists, trust config unless clearly mismatched.
        if isinstance(existing, qmodels.VectorParams):
            if existing.size != vector_size:
                raise ValueError(
                    f"Qdrant collection '{collection_name}' has vector size "
                    f"{existing.size}, expected {vector_size}"
                )
        return
    except ValueError as e:
        # Local mode may raise ValueError("Collection ... not found")
        if "not found" not in str(e).lower():
            raise
    except Exception:
        # If not found or any get error → attempt create.
        pass
    await asyncio.to_thread(
        asyncio.run,
        client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance,
                on_disk=on_disk,
            ),
        ),
    )


async def resolve_qdrant_collection_for_embedding(
    *,
    client: AsyncQdrantClient,
    embedding_id: uuid.UUID,
    vector_size: int,
) -> str:
    """
    Resolve and ensure a tech collection for an embedding model.
    """
    name = qdrant_collection_name_for_embedding(embedding_id)
    await ensure_qdrant_collection(
        client=client,
        collection_name=name,
        vector_size=vector_size,
    )
    return name
