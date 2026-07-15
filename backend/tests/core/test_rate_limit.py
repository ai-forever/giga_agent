"""Tests for the cashews-backed dual-bucket token rate limiter."""

import asyncio
import time
import unittest
import uuid

from cashews import cache

from giga_agent.core.rate_limit import (
    CashewsTokenBucketLimiter,
    _build_bucket,
)


def _make_limiter(
    *,
    requests_global=None,
    requests_per_user=None,
    period_seconds=1,
    user_id="u",
):
    base = f"rl:test:{uuid.uuid4()}"
    return CashewsTokenBucketLimiter(
        global_bucket=_build_bucket(f"{base}:global", requests_global, period_seconds),
        user_bucket=_build_bucket(
            f"{base}:user:{user_id}", requests_per_user, period_seconds
        ),
    ), base


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache.setup("mem://", size=4096)
        await cache.clear()

    async def test_no_buckets_passes_immediately(self):
        limiter = CashewsTokenBucketLimiter(global_bucket=None, user_bucket=None)
        self.assertTrue(await limiter.aacquire(blocking=True))

    async def test_per_user_only_caps_then_refills(self):
        limiter, _ = _make_limiter(requests_per_user=2, period_seconds=1)
        # Capacity = 2 → two immediate acquisitions succeed.
        self.assertTrue(await limiter.aacquire(blocking=False))
        self.assertTrue(await limiter.aacquire(blocking=False))
        # Third is rejected (non-blocking) — bucket empty.
        self.assertFalse(await limiter.aacquire(blocking=False))
        # Blocking acquire waits for a refill, then succeeds.
        started = time.monotonic()
        self.assertTrue(await limiter.aacquire(blocking=True))
        self.assertGreaterEqual(time.monotonic() - started, 0.4)  # ~0.5s for 1 token

    async def test_separate_users_have_independent_buckets(self):
        base = f"rl:test:{uuid.uuid4()}"
        u1 = CashewsTokenBucketLimiter(
            global_bucket=None,
            user_bucket=_build_bucket(f"{base}:user:1", 1, 1),
        )
        u2 = CashewsTokenBucketLimiter(
            global_bucket=None,
            user_bucket=_build_bucket(f"{base}:user:2", 1, 1),
        )
        self.assertTrue(await u1.aacquire(blocking=False))
        self.assertFalse(await u1.aacquire(blocking=False))
        # u2 is unaffected by u1 exhausting its own bucket.
        self.assertTrue(await u2.aacquire(blocking=False))

    async def test_global_bucket_blocks_user_with_tokens_left(self):
        # global 5/s shared; per-user 2/s. Three users share the global key.
        base = f"rl:test:{uuid.uuid4()}"
        period = 1

        def for_user(uid):
            return CashewsTokenBucketLimiter(
                global_bucket=_build_bucket(f"{base}:global", 5, period),
                user_bucket=_build_bucket(f"{base}:user:{uid}", 2, period),
            )

        u1, u2, u3 = for_user(1), for_user(2), for_user(3)
        # user1 x2, user2 x2 → global 5→1
        self.assertTrue(await u1.aacquire(blocking=False))
        self.assertTrue(await u1.aacquire(blocking=False))
        self.assertTrue(await u2.aacquire(blocking=False))
        self.assertTrue(await u2.aacquire(blocking=False))
        # user3 first request → global 1→0 (user3 bucket 2→1)
        self.assertTrue(await u3.aacquire(blocking=False))
        # user3 second request → blocked by the GLOBAL bucket, though user3 still
        # has a per-user token.
        self.assertFalse(await u3.aacquire(blocking=False))

    async def test_concurrent_acquire_never_exceeds_capacity(self):
        limiter, _ = _make_limiter(requests_global=5, period_seconds=1)
        results = await asyncio.gather(
            *[limiter.aacquire(blocking=False) for _ in range(20)]
        )
        # Atomic read-modify-write under the lock → exactly capacity succeed.
        self.assertEqual(sum(1 for r in results if r), 5)


if __name__ == "__main__":
    unittest.main()
