import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.embeddings import router


class EmbeddingsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield object()

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    def _connector_obj(
        self,
        *,
        connector_id: uuid.UUID | None = None,
        connector_type: str = "openai",
        is_active: bool = True,
    ):
        return types.SimpleNamespace(
            id=connector_id or uuid.uuid4(),
            owner_id=self.user.id,
            type=connector_type,
            settings={"api_key": "sk-test"},
            is_active=is_active,
        )

    def _embedding_obj(
        self,
        *,
        embedding_id: uuid.UUID | None = None,
        connector_id: uuid.UUID | None = None,
        embedding_type: str = "openai",
        is_active: bool = True,
        settings: dict | None = None,
    ):
        return types.SimpleNamespace(
            id=embedding_id or uuid.uuid4(),
            owner_id=self.user.id,
            connector_id=connector_id or uuid.uuid4(),
            type=embedding_type,
            model_id="text-embedding-3-small",
            name="main-embedding",
            settings=settings or {},
            is_active=is_active,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _embedding_payload(self, embedding_obj) -> dict:
        return {
            "id": str(embedding_obj.id),
            "owner_id": str(embedding_obj.owner_id),
            "type": embedding_obj.type,
            "connector_id": str(embedding_obj.connector_id),
            "model_id": embedding_obj.model_id,
            "name": embedding_obj.name,
            "settings": embedding_obj.settings,
            "is_active": embedding_obj.is_active,
            "created_at": embedding_obj.created_at,
            "updated_at": embedding_obj.updated_at,
        }

    def test_create_embedding_success(self):
        connector = self._connector_obj()
        created = self._embedding_obj(connector_id=connector.id)

        with patch(
            "giga_agent.routes.embeddings._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ):
            response = self.client.post(
                "/embeddings",
                json={
                    "type": "openai",
                    "connector_id": str(connector.id),
                    "model_id": "text-embedding-3-small",
                    "settings": {},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "openai")
        self.assertEqual(response.json()["connector_id"], str(connector.id))

    def test_models_route_not_shadowed_by_embedding_id_route(self):
        connector = self._connector_obj()
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "text-embedding-3-small", "name": "text-embedding-3-small"}]
            )
        )

        with patch(
            "giga_agent.routes.embeddings._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_for_connector",
            return_value=runtime_cls,
        ):
            response = self.client.get(f"/embeddings/models/{connector.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "text-embedding-3-small")

    def test_fetch_models_for_unsaved_connector(self):
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "EmbeddingsGigaR", "name": "EmbeddingsGigaR"}]
            )
        )

        with patch(
            "giga_agent.routes.embeddings._validate_connector_settings",
            AsyncMock(return_value={"gigachat_credentials": "token"}),
        ), patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_for_connector",
            return_value=runtime_cls,
        ):
            response = self.client.post(
                "/embeddings/models/",
                json={
                    "connector_type": "gigachat",
                    "settings": {"gigachat_credentials": "token"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "EmbeddingsGigaR")

    def test_deactivate_current_auto_clears_current(self):
        self.skipTest("Редактирование эмбеддингов отключено")

    def test_patch_settings_uses_current_embedding_type(self):
        self.skipTest("Редактирование эмбеддингов отключено")

    def test_delete_current_auto_clears_current(self):
        embedding_id = uuid.uuid4()
        existing = self._embedding_obj(embedding_id=embedding_id)

        with patch(
            "giga_agent.routes.embeddings._get_embedding_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.delete",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._clear_current_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current:
            response = self.client.delete(f"/embeddings/{embedding_id}")

        self.assertEqual(response.status_code, 204)
        mocked_clear_current.assert_awaited_once()
