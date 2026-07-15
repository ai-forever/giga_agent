from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from cashews import cache

from giga_agent.conf import get_settings
from giga_agent.connectors.base import BaseConnector


try:
    from gigachat.exceptions import RateLimitError  # type: ignore
except Exception:  # pragma: no cover
    RateLimitError = None  # type: ignore[assignment]


def build_gigachat_token_cache_key(connector_runtime: BaseConnector) -> str:
    """
    Cache key must change when connection/auth settings change.

    We hash the normalized connection kwargs (may include secrets) into a stable fingerprint
    so the final cache key does not leak secrets.
    """
    connection_kwargs = connector_runtime.get_connection_kwargs() or {}
    fingerprint = {
        "connector": f"{connector_runtime.__class__.__module__}.{connector_runtime.__class__.__name__}",
        "connection_kwargs": connection_kwargs,
    }
    payload = json.dumps(
        fingerprint,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"gigachat:token:{digest}"


async def get_gigachat_access_token_cached(
    connector_runtime: BaseConnector,
    *,
    force_refresh: bool = False,
    api_object: Any | None = None,
    max_rate_limit_retries: int = 3,
) -> str:
    """
    Return access token for GigaChat, cached in cashews for 5 minutes.

    Cache key is derived from connector connection kwargs, so changing connector settings
    naturally results in a different cache key (no manual invalidation needed).
    """
    key = build_gigachat_token_cache_key(connector_runtime)
    lock_key = f"{key}:lock"

    if not force_refresh:
        cached = await cache.get(key)
        if isinstance(cached, str) and cached.strip():
            return cached

    async with cache.lock(lock_key, expire=30, wait=True):
        if not force_refresh:
            cached = await cache.get(key)
            if isinstance(cached, str) and cached.strip():
                return cached

        token_str = await get_gigachat_access_token_uncached(
            connector_runtime,
            api_object=api_object,
            max_rate_limit_retries=max_rate_limit_retries,
        )
        await cache.set(key, token_str, expire="5m")
        return token_str


def should_skip_gigachat_token_cache() -> bool:
    return get_settings().giga_agent_gigachat_skip_cache_token


async def get_gigachat_access_token_uncached(
    connector_runtime: BaseConnector,
    *,
    api_object: Any | None = None,
    max_rate_limit_retries: int = 3,
) -> str:
    obj = api_object if api_object is not None else connector_runtime.get_api_object()

    token_data = None
    delay_sec = 0.5
    attempts = max(1, int(max_rate_limit_retries) + 1)
    for attempt_idx in range(attempts):
        try:
            if hasattr(obj, "aget_token"):
                token_data = await obj.aget_token()
            else:
                inner = getattr(obj, "_client", None)
                if inner is not None and hasattr(inner, "aget_token"):
                    token_data = await inner.aget_token()
            break
        except Exception as e:
            if RateLimitError is None or not isinstance(e, RateLimitError):
                raise
            if attempt_idx >= attempts - 1:
                raise
            await asyncio.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 2)

    access_token = (
        getattr(token_data, "access_token", None) if token_data is not None else None
    )
    if not access_token and isinstance(token_data, dict):
        access_token = token_data.get("access_token")

    token_str = str(access_token or "").strip()
    if not token_str:
        raise ValueError(
            "Could not obtain GigaChat access token from connector runtime"
        )

    return token_str
