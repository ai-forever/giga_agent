"""
Module for accessing the Qdrant VectorStore. For local Qdrant, we use
QdrantClient, as it is required for the mem0 module.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from urllib.parse import urlsplit
from functools import cache
from pathlib import Path

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http import models as qmodels

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger


QdrantAnyClient = AsyncQdrantClient | QdrantClient

logger = get_logger(__name__)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def qdrant_call(client: object, method_name: str, /, *args, **kwargs):
    """
    Call Qdrant client method in a compatible way.

    - For sync `QdrantClient` runs in `asyncio.to_thread`.
    - For async client (or test mocks) awaits if needed.
    """
    method = getattr(client, method_name)
    if isinstance(client, QdrantClient):
        return await asyncio.to_thread(method, *args, **kwargs)
    return await _maybe_await(method(*args, **kwargs))


async def _qdrant_aclose(client: object) -> None:
    """Close Qdrant client (sync or async), compatible with AsyncMock in tests."""
    close = getattr(client, "close", None)
    if close is None:
        return
    if isinstance(client, QdrantClient):
        await asyncio.to_thread(close)
        return
    await _maybe_await(close())


def _default_local_storage_path() -> Path:
    from giga_agent.core.paths import ensure_giga_agent_dir

    return ensure_giga_agent_dir() / "qdrant"


def qdrant_connection_config() -> dict[str, str]:
    """
    Normalized Qdrant connection config.

    - If QDRANT_URL is set → remote mode (url + optional api_key)
    - Otherwise → local persistent mode (path)
    """
    url = (os.getenv("QDRANT_URL") or "").strip()
    api_key = (os.getenv("QDRANT_API_KEY") or "").strip()

    if url:
        payload: dict[str, str] = {"url": url}
        if api_key:
            payload["api_key"] = api_key
        return payload

    path = _default_local_storage_path()
    path.mkdir(parents=True, exist_ok=True)
    return {"path": str(path)}


def _parse_pool_size(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    if value.lower() in {"none", "null"}:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def qdrant_pool_size() -> int:
    """
    Connection pool size for remote Qdrant (REST).

    Controlled by env vars:
    - GIGA_AGENT_QDRANT_POOL_SIZE
    - QDRANT_POOL_SIZE (fallback)

    Defaults to 20 (good baseline for 5–20 concurrent requests per process).
    """
    raw = (
        str(get_settings().giga_agent_qdrant_pool_size or "")
        or os.getenv("QDRANT_POOL_SIZE")
        or ""
    )
    return _parse_pool_size(raw) or 20


def _safe_qdrant_url(url: str) -> str:
    """
    Best-effort URL redaction for logs.

    We avoid logging credentials, query params, fragments etc. Only scheme/host/port/path.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
        path = parts.path or ""
        scheme = parts.scheme or "http"
        if host:
            return f"{scheme}://{host}{port}{path}"
        return url
    except Exception:
        return url


@cache
def get_qdrant_client() -> AsyncQdrantClient | QdrantClient:
    """
    Qdrant async client factory.

    Reuses the same env contract as `qdrant_connection_config()`.
    """
    cfg = qdrant_connection_config()
    if "url" in cfg:
        pool_size = qdrant_pool_size()
        logger.info(
            "Using remote Qdrant",
            url=_safe_qdrant_url(cfg["url"]),
            api_key="present" if bool(cfg.get("api_key")) else "absent",
            pool_size=pool_size,
        )
        return AsyncQdrantClient(
            url=cfg["url"],
            api_key=cfg.get("api_key"),
            pool_size=pool_size,
        )
    logger.info("Using local Qdrant", path=cfg["path"])
    return QdrantClient(path=cfg["path"])


async def shutdown_qdrant_client() -> None:
    """
    Best-effort shutdown hook for the cached Qdrant client.

    This is important because `get_qdrant_client()` is cached; closing it per-request
    will poison the cache with a closed client instance.
    """
    try:
        info = get_qdrant_client.cache_info()
        if getattr(info, "currsize", 0) == 0:
            return
    except Exception:
        # If cache metadata is unavailable, proceed best-effort.
        pass

    client = get_qdrant_client()
    try:
        await _qdrant_aclose(client)
    finally:
        try:
            get_qdrant_client.cache_clear()
        except Exception:
            pass


async def ensure_qdrant_collection(
    *,
    client: QdrantAnyClient,
    collection_name: str,
    vector_size: int,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
    on_disk: bool = False,
) -> None:
    """Ensure a Qdrant collection exists with a given vector size."""
    if vector_size <= 0:
        raise ValueError("vector_size must be > 0")

    try:
        info = await qdrant_call(
            client, "get_collection", collection_name=collection_name
        )
        existing = getattr(info.config.params, "vectors", None)
        if isinstance(existing, qmodels.VectorParams) and existing.size != vector_size:
            raise ValueError(
                f"Qdrant collection '{collection_name}' has vector size "
                f"{existing.size}, expected {vector_size}"
            )
        return
    except Exception:
        # Not found or any get error → attempt create.
        pass

    try:
        await qdrant_call(
            client,
            "create_collection",
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance,
                on_disk=on_disk,
            ),
        )
    except Exception:
        # Racy create is OK (already exists / created concurrently).
        return


async def resolve_qdrant_collection(
    *,
    client: QdrantAnyClient,
    collection_name: str,
    vector_size: int,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
    on_disk: bool = False,
) -> str:
    """Resolve and ensure a Qdrant collection by its name."""
    await ensure_qdrant_collection(
        client=client,
        collection_name=collection_name,
        vector_size=vector_size,
        distance=distance,
        on_disk=on_disk,
    )
    return collection_name
