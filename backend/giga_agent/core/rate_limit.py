"""Distributed token-bucket rate limiter backed by cashews.

Enforces two buckets per request — a *global* bucket (shared by all users of a
resource) and a *per-user* bucket. A request acquires one token from each present
bucket atomically: it passes only when **both** buckets have a token, otherwise it
blocks until they do (matching ``langchain_core.rate_limiters.InMemoryRateLimiter``).

State lives in cashews (Redis in production, ``mem://`` locally) so limits survive
restarts and work across workers. Read-modify-write of the buckets is serialized with
a single ``cache.lock`` — the global key's lock when a global limit exists, otherwise
the per-user key's lock. ``asyncio.sleep`` is always performed *outside* the lock.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from cashews import cache
from langchain_core.rate_limiters import BaseRateLimiter
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models.rate_limit import (
    PERIOD_SECONDS,
    RateLimitRepository,
)

# Lock hold guard: a crashed worker must not hold the lock forever.
_LOCK_EXPIRE = 10.0
# Minimum sleep between retries when blocked, to avoid a hot spin.
_MIN_SLEEP = 0.01


@dataclass(frozen=True)
class _BucketConfig:
    key: str
    capacity: float
    refill_rate: float  # tokens per second
    ttl: float


class CashewsTokenBucketLimiter(BaseRateLimiter):
    """Dual-bucket (global + per-user) token-bucket limiter over cashews."""

    def __init__(
        self,
        *,
        global_bucket: _BucketConfig | None,
        user_bucket: _BucketConfig | None,
    ) -> None:
        # Order matters: the lock is taken on the first present bucket. Putting the
        # global bucket first means every request for the resource serializes through
        # the single global lock, under which both buckets are read/written.
        self._buckets: list[_BucketConfig] = [
            b for b in (global_bucket, user_bucket) if b is not None
        ]

    @property
    def _lock_key(self) -> str | None:
        if not self._buckets:
            return None
        return f"{self._buckets[0].key}:lock"

    def acquire(self, *, blocking: bool = True) -> bool:
        # The agent invokes runtimes asynchronously (ainvoke/astream/aembed_*), so the
        # sync path is not exercised. Provide a best-effort fallback for non-loop
        # callers and fail loudly if called from within a running loop.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aacquire(blocking=blocking))
        raise RuntimeError(
            "CashewsTokenBucketLimiter.acquire() called inside a running event loop; "
            "use aacquire() instead."
        )

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if not self._buckets:
            return True

        lock_key = self._lock_key
        while True:
            wait = 0.0
            async with cache.lock(lock_key, expire=_LOCK_EXPIRE):
                now = time.time()
                refilled: list[tuple[_BucketConfig, float]] = []
                all_ok = True
                for bucket in self._buckets:
                    state = await cache.get(bucket.key)
                    if state:
                        tokens = float(state.get("tokens", bucket.capacity))
                        ts = float(state.get("ts", now))
                    else:
                        tokens, ts = bucket.capacity, now
                    elapsed = max(0.0, now - ts)
                    tokens = min(bucket.capacity, tokens + elapsed * bucket.refill_rate)
                    refilled.append((bucket, tokens))
                    if tokens < 1.0:
                        all_ok = False

                if all_ok:
                    for bucket, tokens in refilled:
                        await cache.set(
                            bucket.key,
                            {"tokens": tokens - 1.0, "ts": now},
                            expire=bucket.ttl,
                        )
                    return True

                # Persist the refilled timestamps and compute how long until every
                # short bucket has at least one token.
                for bucket, tokens in refilled:
                    await cache.set(
                        bucket.key,
                        {"tokens": tokens, "ts": now},
                        expire=bucket.ttl,
                    )
                    if tokens < 1.0 and bucket.refill_rate > 0:
                        wait = max(wait, (1.0 - tokens) / bucket.refill_rate)

                if not blocking:
                    return False

            # Sleep OUTSIDE the lock so other users of the resource are not blocked.
            await asyncio.sleep(max(wait, _MIN_SLEEP))


def _build_bucket(key: str, requests: int | None, period_seconds: int) -> _BucketConfig | None:
    if not requests or requests <= 0:
        return None
    capacity = float(requests)
    refill_rate = capacity / float(period_seconds)
    # 2x the time to fully refill from empty, so idle buckets expire on their own.
    ttl = max(float(period_seconds) * 2.0, 10.0)
    return _BucketConfig(
        key=key,
        capacity=capacity,
        refill_rate=refill_rate,
        ttl=ttl,
    )


async def build_runtime_rate_limiter(
    *,
    resource_type: str,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> CashewsTokenBucketLimiter | None:
    """Load the rate-limit config for a resource and build a limiter, or ``None``.

    Returns ``None`` when no active limit is configured (cached, including negatives,
    by :meth:`RateLimitRepository.get_for_resource`).
    """
    cfg = await RateLimitRepository.get_for_resource(
        resource_type,
        resource_id,
        session=session,
    )
    if cfg is None:
        return None

    period_seconds = PERIOD_SECONDS.get(cfg.period)
    if period_seconds is None:
        return None

    base = f"rl:{resource_type}:{resource_id}"
    global_bucket = _build_bucket(f"{base}:global", cfg.requests_global, period_seconds)
    user_bucket = _build_bucket(
        f"{base}:user:{user_id}", cfg.requests_per_user, period_seconds
    )
    if global_bucket is None and user_bucket is None:
        return None

    return CashewsTokenBucketLimiter(
        global_bucket=global_bucket,
        user_bucket=user_bucket,
    )
