from __future__ import annotations

import unittest
import uuid

from cashews import cache

from giga_agent.core.cache import setup_cache
from giga_agent.subagents.leases import (
    SubagentConcurrencyError,
    acquire_lease,
    release_lease,
    update_lease,
)


class SubagentLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        await cache.clear()
        self.user_id = uuid.uuid4()

    async def asyncTearDown(self) -> None:
        await cache.clear()

    async def test_cap_counts_running_and_interrupted_leases(self) -> None:
        leases = [
            await acquire_lease(self.user_id, child_thread_id=f"child-{index}")
            for index in range(3)
        ]
        await update_lease(self.user_id, leases[0].id, state="interrupted")

        with self.assertRaises(SubagentConcurrencyError) as error:
            await acquire_lease(self.user_id, child_thread_id="child-over-limit")
        self.assertEqual(error.exception.code, "SUBAGENT_CONCURRENCY_LIMIT")

        await release_lease(self.user_id, leases[1].id)
        replacement = await acquire_lease(
            self.user_id, child_thread_id="child-replacement"
        )
        self.assertIsNotNone(replacement.id)
