from __future__ import annotations

import asyncio
import uuid

from cashews import LockedError, cache

from giga_agent.core.events import event_bus
from giga_agent.core.logging import get_logger
from giga_agent.memory.backends import get_backend
from giga_agent.memory.service import MemoryService, _collection_name
from giga_agent.modules.auth.events import UserEmbeddingChangedEvent
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    qdrant_call,
)


logger = get_logger(__name__)
_SUBSCRIBED = False
_LOCK = asyncio.Lock()

# Cross-instance lock for embedding-change migration so the heavy work
# (qdrant wipe + reindex) runs on a single worker per user even when the
# event is observed by multiple processes. With Redis cashews backend this
# is a real distributed lock; with the in-memory backend it degrades to a
# per-process lock — which is still correct for single-instance setups.
_MIGRATION_LOCK_TTL_SECONDS = 30 * 60
_MIGRATION_LOCK_CHECK_INTERVAL = 0.5


async def _drop_collection_points(*, collection: str, owner_id: uuid.UUID) -> None:
    from qdrant_client.http import models as qmodels

    client = get_qdrant_client()
    flt = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="owner_id",
                match=qmodels.MatchValue(value=str(owner_id)),
            )
        ]
    )
    try:
        await qdrant_call(
            client,
            "delete",
            collection_name=collection,
            points_selector=qmodels.FilterSelector(filter=flt),
        )
    except Exception:
        logger.warning(
            "Failed to delete memory points (collection may not exist)",
            extra={"collection": collection, "owner_id": str(owner_id)},
        )


async def _reindex_with_new_embedding(
    *, user_id: uuid.UUID, new_embedding_id: uuid.UUID
) -> None:
    from giga_agent.core.db import get_session_factory
    from giga_agent.embeddings.manager import EmbeddingManager
    from giga_agent.models.users import UserRepository

    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(user_id, session=session)
        if user is None:
            return
        embedding_runtime = await EmbeddingManager.resolve_by_id(
            new_embedding_id, session=session
        )

    backend = get_backend()
    service = MemoryService(
        backend=backend,
        owner_id=user_id,
        embedding_runtime=embedding_runtime,
        embedding_id=new_embedding_id,
        fast_llm=None,
    )
    # Mark all files as needing reindex first, then run it.
    await backend.reset_indexed_for_owner(owner_id=user_id)
    await service.reindex_changed()


def _migration_lock_key(user_id: uuid.UUID) -> str:
    return f"memory:embedding_migration:{user_id}"


async def _migrate(event: UserEmbeddingChangedEvent) -> None:
    if event.old_embedding_id is not None:
        await _drop_collection_points(
            collection=_collection_name(event.old_embedding_id),
            owner_id=event.user_id,
        )
    backend = get_backend()
    await backend.reset_indexed_for_owner(owner_id=event.user_id)
    if event.new_embedding_id is not None:
        await _reindex_with_new_embedding(
            user_id=event.user_id,
            new_embedding_id=event.new_embedding_id,
        )


async def _handle_embedding_change(event: UserEmbeddingChangedEvent) -> None:
    async def _runner() -> None:
        lock_key = _migration_lock_key(event.user_id)
        try:
            async with cache.lock(
                lock_key,
                expire=_MIGRATION_LOCK_TTL_SECONDS,
                wait=False,
                check_interval=_MIGRATION_LOCK_CHECK_INTERVAL,
            ):
                await _migrate(event)
        except LockedError:
            logger.info(
                "Memory embedding migration skipped: another instance is "
                "already handling it (user=%s)",
                event.user_id,
            )
            return
        except Exception as exc:
            # cashews not configured (e.g. unit tests, CLI without cache setup)
            # — fall back to running the migration without the lock so we
            # don't silently drop the event.
            if exc.__class__.__name__ == "NotConfiguredError":
                logger.debug(
                    "Cashews not configured — running memory migration without lock"
                )
                try:
                    await _migrate(event)
                except Exception:
                    logger.exception(
                        "Memory migration failed (no lock, user=%s)",
                        event.user_id,
                    )
                return
            logger.exception(
                "Memory migration failed (user=%s, %s → %s)",
                event.user_id,
                event.old_embedding_id,
                event.new_embedding_id,
            )

    asyncio.create_task(_runner())


async def ensure_subscribed() -> None:
    global _SUBSCRIBED
    async with _LOCK:
        if _SUBSCRIBED:
            return
        event_bus.subscribe(UserEmbeddingChangedEvent, _handle_embedding_change)
        _SUBSCRIBED = True


__all__ = ["ensure_subscribed"]
