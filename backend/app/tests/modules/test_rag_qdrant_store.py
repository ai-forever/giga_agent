import asyncio
import unittest
import uuid

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http import models as qmodels

from giga_agent.vectorstores.qdrant import ensure_qdrant_collection, qdrant_aclose
from giga_agent.modules.rag.database.qdrant_store import (
    build_filter,
    delete_by_filter,
    search_chunks,
    upsert_chunks,
)


class RagQdrantStoreTests(unittest.TestCase):
    def test_upsert_search_delete(self) -> None:
        asyncio.run(self._test_upsert_search_delete())

    async def _test_upsert_search_delete(self) -> None:
        for client in (AsyncQdrantClient(":memory:"), QdrantClient(path=":memory:")):
            try:
                collection_name = "test_rag_chunks"
                await ensure_qdrant_collection(
                    client=client, collection_name=collection_name, vector_size=3
                )

                owner_id = uuid.uuid4()
                coll_id = uuid.uuid4()
                other_owner = uuid.uuid4()
                p1 = str(uuid.uuid4())
                p2 = str(uuid.uuid4())

                points = [
                    qmodels.PointStruct(
                        id=p1,
                        vector=[1.0, 0.0, 0.0],
                        payload={
                            "owner_id": str(owner_id),
                            "collection_id": str(coll_id),
                            "page_content": "alpha",
                        },
                    ),
                    qmodels.PointStruct(
                        id=p2,
                        vector=[1.0, 0.0, 0.0],
                        payload={
                            "owner_id": str(other_owner),
                            "collection_id": str(coll_id),
                            "page_content": "beta",
                        },
                    ),
                ]
                await upsert_chunks(
                    client=client, collection_name=collection_name, points=points
                )

                qfilter = build_filter(owner_id=owner_id, collection_id=coll_id)
                results = await search_chunks(
                    client=client,
                    collection_name=collection_name,
                    query_vector=[1.0, 0.0, 0.0],
                    query_filter=qfilter,
                    limit=10,
                )
                self.assertEqual(len(results), 1)
                self.assertEqual(str(results[0].id), p1)

                await delete_by_filter(
                    client=client, collection_name=collection_name, query_filter=qfilter
                )
                results2 = await search_chunks(
                    client=client,
                    collection_name=collection_name,
                    query_vector=[1.0, 0.0, 0.0],
                    query_filter=qfilter,
                    limit=10,
                )
                self.assertEqual(len(results2), 0)
            finally:
                await qdrant_aclose(client)

