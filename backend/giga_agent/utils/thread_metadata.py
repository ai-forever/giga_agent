"""Live thread metadata, cache-first with a langgraph-SDK fallback.

``auto_approve`` / ``thread_title`` live in the langgraph thread metadata. The
value passed in a run's ``config["metadata"]`` is a snapshot taken at run
creation and does not reflect updates made mid-run (e.g. the user toggling
autonomy from the frontend). Reading through this module gives middlewares the
current value: it serves from the cashews cache when warm and falls back to
``client.threads.get`` on a miss, refreshing the cache.

Writers (the autonomy endpoint, the title middleware, the before_agent sync)
go through :func:`update_thread_metadata` so the cache stays in step with the
backing store in the same call site that mutates it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from giga_agent.core.cache import setup_cache
from giga_agent.core.logging import get_logger
from giga_agent.utils.langgraph_sdk import get_client

logger = get_logger(__name__)

_CACHE_KEY = "thread:metadata:{thread_id}"
_CACHE_TTL = "10m"


def _is_persistable(thread_id: str | None) -> bool:
    return bool(thread_id) and not thread_id.startswith("temporary/")


def _key(thread_id: str) -> str:
    return _CACHE_KEY.format(thread_id=thread_id)


def _cache():
    # Idempotent; ensures a backend exists when a middleware runs before startup.
    setup_cache()
    from cashews import cache

    return cache


async def get_thread_metadata(
    config: RunnableConfig, thread_id: str | None
) -> dict[str, Any]:
    """Current thread metadata, cache-first with an SDK fallback.

    Returns an empty dict for temporary/unknown threads or on any failure, so
    callers can treat it like ``config.get("metadata")`` without extra guards.
    """
    if not _is_persistable(thread_id):
        return {}

    cache = _cache()
    cached = await cache.get(_key(thread_id))
    if cached is not None:
        return cached

    try:
        thread = await get_client(config).threads.get(thread_id)
        meta = (thread or {}).get("metadata") or {}
    except Exception as exc:
        logger.debug("thread_metadata_fetch_failed", thread_id=thread_id, error=str(exc))
        return {}

    await cache.set(_key(thread_id), meta, expire=_CACHE_TTL)
    return meta


async def update_thread_metadata(
    config: RunnableConfig, thread_id: str | None, updates: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``updates`` into thread metadata via the SDK and refresh the cache."""
    if not _is_persistable(thread_id):
        return {}

    cache = _cache()
    thread = await get_client(config).threads.update(thread_id, metadata=updates)
    meta = (thread or {}).get("metadata") or {}
    # client.threads.update merges and returns the full metadata; fall back to a
    # local merge if the server response omits it.
    if not meta:
        prev = await cache.get(_key(thread_id)) or {}
        meta = {**prev, **updates}
    await cache.set(_key(thread_id), meta, expire=_CACHE_TTL)
    return meta


async def invalidate_thread_metadata(thread_id: str | None) -> None:
    if not _is_persistable(thread_id):
        return
    await _cache().delete(_key(thread_id))
