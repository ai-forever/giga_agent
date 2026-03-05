from __future__ import annotations

import asyncio
import inspect
import uuid
from pathlib import Path
from typing import Any

from mem0 import AsyncMemory
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    qdrant_connection_config,
    resolve_qdrant_collection,
)

logger = get_logger(__name__)


class MemZeroEmbeddingsNotConfigured(RuntimeError):
    """Raised when user has no embedding model configured."""


# Cache of ensured collections (per-process) to avoid repeated I/O on every request.
# Maps collection_name -> vector_size that was ensured.
_ENSURED_COLLECTIONS: dict[str, int] = {}
_ENSURED_LOCK = asyncio.Lock()
_MIGRATION_LOCKS: dict[uuid.UUID, asyncio.Lock] = {}
_MIGRATION_LOCKS_GUARD = asyncio.Lock()
_MIGRATION_BATCH_SIZE = 100
_MIGRATION_GET_ALL_LIMIT = 100_000


def _qdrant_ensure_cache_enabled() -> bool:
    """
    Controls per-process caching of Qdrant ensure() calls.

    Default: enabled. Set env var explicitly to disable:
      GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE=0|false
    """
    return get_settings().giga_agent_mem0_qdrant_ensure_cache


def _mem0_collection_name_for_embedding(embedding_id: uuid.UUID) -> str:
    # Keep names simple ASCII for compatibility.
    return f"mem0__{embedding_id.hex}"


def _default_mem0_storage_path() -> Path:
    from giga_agent.core.paths import ensure_giga_agent_dir

    d = ensure_giga_agent_dir() / "mem0"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.db"


async def get_memory_for_user(*, user: UserShort, session: AsyncSession) -> AsyncMemory:
    """
    Build an AsyncMemory instance for a concrete user configuration.

    Note: this function is intentionally NOT cached to ensure DB-driven changes
    (embedding_id / llm_id updates) are reflected immediately.
    """
    return await _get_memory_for_user_with_embedding_id(
        user=user,
        session=session,
        embedding_id=user.embedding_id,
    )


async def _get_memory_for_user_with_embedding_id(
    *,
    user: UserShort,
    session: AsyncSession,
    embedding_id: uuid.UUID | None,
) -> AsyncMemory:
    if embedding_id is None:
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

    embedding_runtime = await EmbeddingManager.resolve_by_id(
        embedding_id,
        session=session,
    )
    embeddings = await embedding_runtime.get_embeddings()
    vector_size = int(embedding_runtime.vector_size)

    llm_runtime = await LLMManager.resolve_by_id(llm_id, session=session)
    llm = await llm_runtime.get_llm()

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
        "history_db_path": str(_default_mem0_storage_path()),
    }

    return await AsyncMemory.from_config(config)


async def _get_migration_lock(user_id: uuid.UUID) -> asyncio.Lock:
    async with _MIGRATION_LOCKS_GUARD:
        existing = _MIGRATION_LOCKS.get(user_id)
        if existing is not None:
            return existing
        created = asyncio.Lock()
        _MIGRATION_LOCKS[user_id] = created
        return created


async def _extract_results(
    payload: dict[str, Any] | list[Any] | None,
) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        if inspect.iscoroutine(results):
            return await results
    return []


def _records_to_messages(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in records:
        content = item.get("memory")
        if not isinstance(content, str) or not content.strip():
            continue
        role_raw = item.get("role")
        role = role_raw if role_raw in {"user", "assistant"} else "user"
        messages.append({"role": role, "content": content})
    return messages


def _iter_chunks(
    items: list[dict[str, str]], *, size: int
) -> list[list[dict[str, str]]]:
    if size <= 0:
        return [items]
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


async def migrate_user_memories_for_embedding_change(
    *,
    user_id: uuid.UUID,
    old_embedding_id: uuid.UUID | None,
    new_embedding_id: uuid.UUID | None,
) -> None:
    if old_embedding_id == new_embedding_id:
        return
    if old_embedding_id is None and new_embedding_id is not None:
        # There is no old collection to migrate from.
        return

    migration_lock = await _get_migration_lock(user_id)
    async with migration_lock:
        session_factory = await get_session_factory()
        async with session_factory() as session:
            user = await UserRepository.get_cached_or_db(user_id, session=session)
            if user is None:
                return

            if user.llm_id is None and user.fast_llm_id is None:
                logger.warning(
                    "mem0 migration skipped: no llm configured",
                    user_id=str(user_id),
                    old_embedding_id=(
                        str(old_embedding_id) if old_embedding_id else None
                    ),
                    new_embedding_id=(
                        str(new_embedding_id) if new_embedding_id else None
                    ),
                )
                return

            if old_embedding_id is not None and new_embedding_id is None:
                old_memory = await _get_memory_for_user_with_embedding_id(
                    user=user,
                    session=session,
                    embedding_id=old_embedding_id,
                )
                await old_memory.delete_all(user_id=str(user_id))
                return

            if old_embedding_id is None or new_embedding_id is None:
                return

            old_memory = await _get_memory_for_user_with_embedding_id(
                user=user,
                session=session,
                embedding_id=old_embedding_id,
            )
            old_raw = await old_memory.get_all(
                user_id=str(user_id),
                limit=_MIGRATION_GET_ALL_LIMIT,
            )
            old_records = await _extract_results(old_raw)
            messages = _records_to_messages(old_records)
            if not messages:
                await old_memory.delete_all(user_id=str(user_id))
                return

            new_memory = await _get_memory_for_user_with_embedding_id(
                user=user,
                session=session,
                embedding_id=new_embedding_id,
            )
            for batch in _iter_chunks(messages, size=_MIGRATION_BATCH_SIZE):
                await new_memory.add(batch, user_id=str(user_id), infer=False)

            await old_memory.delete_all(user_id=str(user_id))


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
