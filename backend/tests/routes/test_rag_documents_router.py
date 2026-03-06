import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.rag.api.documents import router as documents_router


class RagDocumentsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.db = types.SimpleNamespace()

        app = FastAPI()
        app.include_router(documents_router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield self.db

        app.dependency_overrides[get_current_active_user] = _override_current_user
        app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(app)

    def test_delete_document_deletes_from_qdrant_and_s3(self) -> None:
        collection_id = uuid.uuid4()
        document_id = uuid.uuid4()
        embedding_id = uuid.uuid4()

        collections_repo = Mock()
        collections_repo.get_by_id_any = AsyncMock(
            return_value=types.SimpleNamespace(
                id=collection_id,
                embedding_id=embedding_id,
                owner_id=self.user.id,
            )
        )

        docs_repo = Mock()
        docs_repo.get_by_id = AsyncMock(
            return_value=types.SimpleNamespace(
                id=document_id,
                sandbox_path=f"/bucket/giga_agent/{self.user.id}/rag/doc.txt",
            )
        )
        docs_repo.delete = AsyncMock(return_value=True)

        qdrant_client = Mock()
        qdrant_client.close = AsyncMock()

        runtime = types.SimpleNamespace(vector_size=3)

        with patch(
            "giga_agent.modules.rag.api.documents.RagCollectionsRepository",
            return_value=collections_repo,
        ), patch(
            "giga_agent.modules.rag.api.documents.RagDocumentsRepository",
            return_value=docs_repo,
        ), patch(
            "giga_agent.modules.rag.api.documents.EmbeddingManager.resolve_by_id",
            AsyncMock(return_value=runtime),
        ), patch(
            "giga_agent.modules.rag.api.documents.get_qdrant_client",
            return_value=qdrant_client,
        ), patch(
            "giga_agent.modules.rag.api.documents.resolve_qdrant_collection",
            AsyncMock(return_value="rag_chunks__test"),
        ), patch(
            "giga_agent.modules.rag.api.documents.build_filter",
            return_value=object(),
        ), patch(
            "giga_agent.modules.rag.api.documents.delete_by_filter",
            AsyncMock(return_value=None),
        ) as mocked_delete_by_filter, patch(
            "giga_agent.modules.rag.api.documents.SandboxManager.delete_file_by_path_for_user",
            AsyncMock(return_value=None),
        ) as mocked_delete_file_by_path, patch(
            "giga_agent.modules.rag.api.documents.SandboxManager.__init__",
            return_value=None,
        ):
            resp = self.client.delete(
                f"/collections/{collection_id}/documents/{document_id}"
            )

        self.assertEqual(resp.status_code, 200)
        mocked_delete_by_filter.assert_awaited_once()
        mocked_delete_file_by_path.assert_awaited_once()
        docs_repo.delete.assert_awaited_once_with(
            owner_id=self.user.id,
            collection_id=collection_id,
            document_id=document_id,
        )

    def test_delete_document_404_when_missing(self) -> None:
        collection_id = uuid.uuid4()
        document_id = uuid.uuid4()
        embedding_id = uuid.uuid4()

        collections_repo = Mock()
        collections_repo.get_by_id_any = AsyncMock(
            return_value=types.SimpleNamespace(
                id=collection_id,
                embedding_id=embedding_id,
                owner_id=self.user.id,
            )
        )

        docs_repo = Mock()
        docs_repo.get_by_id = AsyncMock(return_value=None)
        docs_repo.delete = AsyncMock(return_value=False)

        with patch(
            "giga_agent.modules.rag.api.documents.RagCollectionsRepository",
            return_value=collections_repo,
        ), patch(
            "giga_agent.modules.rag.api.documents.RagDocumentsRepository",
            return_value=docs_repo,
        ), patch(
            "giga_agent.modules.rag.api.documents.delete_by_filter",
            AsyncMock(return_value=None),
        ) as mocked_delete_by_filter, patch(
            "giga_agent.modules.rag.api.documents.SandboxManager.delete_file_by_path_for_user",
            AsyncMock(return_value=None),
        ) as mocked_delete_file_by_path, patch(
            "giga_agent.modules.rag.api.documents.SandboxManager.__init__",
            return_value=None,
        ):
            resp = self.client.delete(
                f"/collections/{collection_id}/documents/{document_id}"
            )

        self.assertEqual(resp.status_code, 404)
        mocked_delete_by_filter.assert_not_awaited()
        mocked_delete_file_by_path.assert_not_awaited()
        docs_repo.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
