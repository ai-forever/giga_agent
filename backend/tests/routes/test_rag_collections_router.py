import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.rag.api.collections import router as collections_router


class RagCollectionsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.db = types.SimpleNamespace()

        app = FastAPI()
        app.include_router(collections_router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield self.db

        app.dependency_overrides[get_current_active_user] = _override_current_user
        app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(app)

    def test_delete_collection_deletes_from_qdrant(self) -> None:
        collection_id = uuid.uuid4()
        embedding_id = uuid.uuid4()

        repo_instance = Mock()
        collection = types.SimpleNamespace(
            id=collection_id,
            embedding_id=embedding_id,
            owner_id=self.user.id,
        )
        repo_instance.get_by_id_with_access_for_user = AsyncMock(
            return_value=(collection, True, True)
        )
        repo_instance.delete = AsyncMock(return_value=True)

        qdrant_client = Mock()
        qdrant_client.close = AsyncMock()

        runtime = types.SimpleNamespace(vector_size=3)
        docs_repo_instance = Mock()
        docs_repo_instance.list_by_collection = AsyncMock(
            side_effect=[
                [
                    types.SimpleNamespace(
                        sandbox_path="/bucket/rag1.txt"
                    )
                ],
                [],
            ]
        )

        with patch(
            "giga_agent.modules.rag.api.collections.RagCollectionsRepository",
            return_value=repo_instance,
        ), patch(
            "giga_agent.modules.rag.api.collections.RagDocumentsRepository",
            return_value=docs_repo_instance,
        ), patch(
            "giga_agent.modules.rag.api.collections.SandboxManager.delete_file_by_path_for_user",
            AsyncMock(return_value=None),
        ) as mocked_delete_file_by_path, patch(
            "giga_agent.modules.rag.api.collections.SandboxManager.__init__",
            return_value=None,
        ), patch(
            "giga_agent.modules.rag.api.collections.EmbeddingManager.resolve_by_id",
            AsyncMock(return_value=runtime),
        ), patch(
            "giga_agent.modules.rag.api.collections.get_qdrant_client",
            return_value=qdrant_client,
        ), patch(
            "giga_agent.modules.rag.api.collections.resolve_qdrant_collection",
            AsyncMock(return_value="rag_chunks__test"),
        ), patch(
            "giga_agent.modules.rag.api.collections.build_filter",
            return_value=object(),
        ) as mocked_build_filter, patch(
            "giga_agent.modules.rag.api.collections.delete_by_filter",
            AsyncMock(return_value=None),
        ) as mocked_delete_by_filter:
            resp = self.client.delete(f"/collections/{collection_id}")

        self.assertEqual(resp.status_code, 204)
        mocked_delete_file_by_path.assert_awaited()
        mocked_build_filter.assert_called_once_with(
            owner_id=self.user.id,
            collection_id=collection_id,
        )
        mocked_delete_by_filter.assert_awaited_once()
        repo_instance.delete.assert_awaited_once_with(
            owner_id=self.user.id,
            collection_id=collection_id,
        )

    def test_delete_collection_404_when_missing(self) -> None:
        collection_id = uuid.uuid4()

        repo_instance = Mock()
        repo_instance.get_by_id_with_access_for_user = AsyncMock(return_value=None)

        with patch(
            "giga_agent.modules.rag.api.collections.RagCollectionsRepository",
            return_value=repo_instance,
        ), patch(
            "giga_agent.modules.rag.api.collections.RagDocumentsRepository",
            return_value=Mock(),
        ) as mocked_docs_repo, patch(
            "giga_agent.modules.rag.api.collections.SandboxManager.delete_file_by_path_for_user",
            AsyncMock(return_value=None),
        ) as mocked_delete_file_by_path, patch(
            "giga_agent.modules.rag.api.collections.SandboxManager.__init__",
            return_value=None,
        ), patch(
            "giga_agent.modules.rag.api.collections.delete_by_filter",
            AsyncMock(return_value=None),
        ) as mocked_delete_by_filter:
            resp = self.client.delete(f"/collections/{collection_id}")

        self.assertEqual(resp.status_code, 404)
        mocked_docs_repo.assert_not_called()
        mocked_delete_file_by_path.assert_not_awaited()
        mocked_delete_by_filter.assert_not_awaited()

    def test_list_collections_includes_can_edit(self) -> None:
        owned = types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            name="owned",
            metadata_={},
        )
        writable = types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="writable",
            metadata_={},
        )
        readonly = types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="readonly",
            metadata_={},
        )
        repo_instance = Mock()
        repo_instance.list_readable_with_edit_for_user = AsyncMock(
            return_value=[
                (owned, True),
                (writable, True),
                (readonly, False),
            ]
        )

        with patch(
            "giga_agent.modules.rag.api.collections.RagCollectionsRepository",
            return_value=repo_instance,
        ):
            resp = self.client.get("/collections")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        can_edit_by_id = {item["uuid"]: item["can_edit"] for item in payload}
        self.assertTrue(can_edit_by_id[str(owned.id)])
        self.assertTrue(can_edit_by_id[str(writable.id)])
        self.assertFalse(can_edit_by_id[str(readonly.id)])


if __name__ == "__main__":
    unittest.main()
