from __future__ import annotations

import asyncio
import os
import uuid

from mem0 import AsyncMemory
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserShort
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    qdrant_connection_config,
    resolve_qdrant_collection,
)


class MemZeroEmbeddingsNotConfigured(RuntimeError):
    """Raised when user has no embedding model configured."""


# Cache of ensured collections (per-process) to avoid repeated I/O on every request.
# Maps collection_name -> vector_size that was ensured.
_ENSURED_COLLECTIONS: dict[str, int] = {}
_ENSURED_LOCK = asyncio.Lock()


def _qdrant_ensure_cache_enabled() -> bool:
    """
    Controls per-process caching of Qdrant ensure() calls.

    Default: enabled. Set env var explicitly to disable:
      GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE=0|false
    """
    raw = (os.getenv("GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE") or "").strip()
    if raw in {"0", "false", "False"}:
        return False
    return True


def _mem0_collection_name_for_embedding(embedding_id: uuid.UUID) -> str:
    # Keep names simple ASCII for compatibility.
    return f"mem0__{embedding_id.hex}"


async def get_memory_for_user(*, user: UserShort, session: AsyncSession) -> AsyncMemory:
    """
    Build an AsyncMemory instance for a concrete user configuration.

    Note: this function is intentionally NOT cached to ensure DB-driven changes
    (embedding_id / llm_id updates) are reflected immediately.
    """
    if user.embedding_id is None:
        raise MemZeroEmbeddingsNotConfigured(
            "Embeddings are not configured for this user. "
            "Set `embedding_id` on the user to enable mem0 memory."
        )

    llm_id = user.fast_llm_id or user.llm_id
    if llm_id is None:
        raise ValueError(
            "User has no LLM configured for mem0. "
            "Set `llm_id` (and optionally `fast_llm_id`) on the user."
        )

    embedding_id = user.embedding_id
    embedding_runtime = await EmbeddingManager.resolve_by_id(
        embedding_id,
        session=session,
    )
    embeddings = embedding_runtime.embeddings
    vector_size = int(embedding_runtime.vector_size)

    llm_runtime = await LLMManager.resolve_by_id(llm_id, session=session)
    llm = llm_runtime.llm

    collection_name = _mem0_collection_name_for_embedding(embedding_id)
    already_ensured = False
    if _qdrant_ensure_cache_enabled():
        async with _ENSURED_LOCK:
            already_ensured = _ENSURED_COLLECTIONS.get(collection_name) == vector_size

    if not already_ensured:
        qdrant_client = get_qdrant_client()
        await resolve_qdrant_collection(
            client=qdrant_client,
            collection_name=collection_name,
            vector_size=vector_size,
        )

        if _qdrant_ensure_cache_enabled():
            async with _ENSURED_LOCK:
                _ENSURED_COLLECTIONS[collection_name] = vector_size
    qdrant_config = qdrant_connection_config()
    if "path" in qdrant_config:
        qdrant_config["client"] = get_qdrant_client()
    config = {
        "embedder": {
            "provider": "langchain",
            "config": {"model": embeddings, "embedding_dims": vector_size},
        },
        "llm": {"provider": "langchain", "config": {"model": llm}},
        "vector_store": {
            "provider": "qdrant",
            "config": {
                **qdrant_config,
                "collection_name": collection_name,
                "embedding_model_dims": vector_size,
            },
        },
    }

    return await AsyncMemory.from_config(config)


def format_memories(memories: dict) -> str:
    if not memories.get("results"):
        return ""
    formatted = "\n".join([f"- {m['memory']}" for m in memories["results"]])
    return f"""
====
ДОЛГОСРОЧНАЯ ПАМЯТЬ
Ниже приведены воспоминания о прошлых взаимодействиях с этим пользователем. 
Используй их, чтобы поддерживать контекст и персонализировать ответы.

{formatted}
====
"""
