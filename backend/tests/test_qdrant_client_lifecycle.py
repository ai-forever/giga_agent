import asyncio
import os
import unittest

from giga_agent.vectorstores.qdrant import get_qdrant_client, shutdown_qdrant_client


class QdrantClientLifecycleTests(unittest.TestCase):
    def test_shutdown_clears_cached_client(self) -> None:
        asyncio.run(self._test_shutdown_clears_cached_client())

    async def _test_shutdown_clears_cached_client(self) -> None:
        # Force local mode to avoid any accidental network dependency in CI/dev env.
        os.environ.pop("QDRANT_URL", None)
        os.environ.pop("QDRANT_API_KEY", None)

        get_qdrant_client.cache_clear()

        # Should be a no-op if client was never created.
        await shutdown_qdrant_client()

        c1 = get_qdrant_client()
        self.assertEqual(get_qdrant_client.cache_info().currsize, 1)

        await shutdown_qdrant_client()
        self.assertEqual(get_qdrant_client.cache_info().currsize, 0)

        c2 = get_qdrant_client()
        self.assertIsNot(c1, c2)

        # Cleanup (best-effort).
        await shutdown_qdrant_client()


if __name__ == "__main__":
    unittest.main()

