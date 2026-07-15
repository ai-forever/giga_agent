import asyncio
import os
import unittest
from unittest.mock import patch

from giga_agent.vectorstores.qdrant import get_qdrant_client, shutdown_qdrant_client


class _FakeAsyncClient:
    """Stand-in for AsyncQdrantClient that never touches the network/disk."""

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class QdrantClientLifecycleTests(unittest.TestCase):
    def test_shutdown_clears_cached_client(self) -> None:
        asyncio.run(self._test_shutdown_clears_cached_client())

    async def _test_shutdown_clears_cached_client(self) -> None:
        # Use remote mode with a fake client: the local on-disk QdrantClient is
        # intentionally not closed on shutdown (SQLite cross-thread safety), so it
        # would keep the storage folder locked and can't be reopened here.
        get_qdrant_client.cache_clear()

        with (
            patch.dict(
                os.environ, {"QDRANT_URL": "http://localhost:6333"}, clear=False
            ),
            patch("giga_agent.vectorstores.qdrant.AsyncQdrantClient", _FakeAsyncClient),
        ):
            os.environ.pop("QDRANT_API_KEY", None)

            # Should be a no-op if client was never created.
            await shutdown_qdrant_client()

            c1 = get_qdrant_client()
            self.assertEqual(get_qdrant_client.cache_info().currsize, 1)

            await shutdown_qdrant_client()
            self.assertEqual(get_qdrant_client.cache_info().currsize, 0)
            self.assertTrue(c1.closed)

            c2 = get_qdrant_client()
            self.assertIsNot(c1, c2)

            # Cleanup (best-effort).
            await shutdown_qdrant_client()

        get_qdrant_client.cache_clear()


if __name__ == "__main__":
    unittest.main()
