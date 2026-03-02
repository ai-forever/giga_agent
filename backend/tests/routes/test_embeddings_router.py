import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.auth.events import UserEmbeddingChangedEvent
from giga_agent.routes.embeddings import router


class EmbeddingsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(), is_active=True, is_superuser=True
        )
        self.db = types.SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield self.db

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
        user_model = types.SimpleNamespace(embedding_id=created.id)

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
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

    def test_create_embedding_skips_connection_check_when_disabled(self):
        connector = self._connector_obj()
        created = self._embedding_obj(connector_id=connector.id)
        user_model = types.SimpleNamespace(embedding_id=created.id)

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ) as mocked_check, patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
        ):
            response = self.client.post(
                "/embeddings",
                json={
                    "type": "openai",
                    "connector_id": str(connector.id),
                    "model_id": "text-embedding-3-small",
                    "settings": {},
                    "is_active": True,
                    "check_connection": False,
                },
            )

        self.assertEqual(response.status_code, 201)
        mocked_check.assert_not_awaited()

    def test_create_embedding_returns_422_when_connection_check_fails(self):
        connector = self._connector_obj()

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(side_effect=HTTPException(status_code=422, detail="boom")),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(),
        ) as mocked_create:
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

        self.assertEqual(response.status_code, 422)
        mocked_create.assert_not_awaited()

    def test_create_embedding_allows_read_access_to_foreign_connector(self):
        connector = self._connector_obj()
        connector.owner_id = uuid.uuid4()
        created = self._embedding_obj(connector_id=connector.id)
        user_model = types.SimpleNamespace(embedding_id=created.id)
        runtime_cls = types.SimpleNamespace(supported_connector_types=lambda: ["openai"])

        with patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime",
            return_value=runtime_cls,
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id_with_access_for_user",
            AsyncMock(return_value=(connector, True, False)),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
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
        self.assertEqual(response.json()["connector_id"], str(connector.id))

    def test_create_embedding_with_permissions_for_superuser(self):
        connector = self._connector_obj()
        created = self._embedding_obj(connector_id=connector.id)
        user_model = types.SimpleNamespace(embedding_id=created.id)

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.ResourcePermissionRepository.set_read_acl",
            AsyncMock(return_value=None),
        ) as mocked_set_acl, patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
        ):
            response = self.client.post(
                "/embeddings",
                json={
                    "type": "openai",
                    "connector_id": str(connector.id),
                    "model_id": "text-embedding-3-small",
                    "settings": {},
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [str(uuid.uuid4())],
                        "public_read": True,
                    },
                },
            )

        self.assertEqual(response.status_code, 201)
        mocked_set_acl.assert_awaited_once()

    def test_create_embedding_with_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(),
        ) as mocked_get_connector:
            response = self.client.post(
                "/embeddings",
                json={
                    "type": "openai",
                    "connector_id": str(uuid.uuid4()),
                    "model_id": "text-embedding-3-small",
                    "settings": {},
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [],
                        "public_read": False,
                    },
                },
            )

        self.assertEqual(response.status_code, 403)
        mocked_get_connector.assert_not_awaited()

    def test_create_first_embedding_auto_sets_user_embedding_id(self):
        connector = self._connector_obj()
        created = self._embedding_obj(connector_id=connector.id)
        user_model = types.SimpleNamespace(embedding_id=None)

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.routes.embeddings.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_invalidate_cache, patch(
            "giga_agent.routes.embeddings.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
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
        self.assertEqual(user_model.embedding_id, created.id)
        self.db.commit.assert_awaited()
        self.db.refresh.assert_awaited()
        mocked_invalidate_cache.assert_awaited_once_with(self.user.id)
        mocked_publish.assert_awaited_once()
        event = mocked_publish.await_args.args[0]
        self.assertIsInstance(event, UserEmbeddingChangedEvent)
        self.assertEqual(event.user_id, self.user.id)
        self.assertIsNone(event.old_embedding_id)
        self.assertEqual(event.new_embedding_id, created.id)

    def test_create_next_embedding_does_not_change_user_embedding_id(self):
        connector = self._connector_obj()
        created = self._embedding_obj(connector_id=connector.id)
        current_embedding_id = uuid.uuid4()
        user_model = types.SimpleNamespace(embedding_id=current_embedding_id)

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.embeddings._check_connection_or_http_error",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings._probe_embedding_vector_size",
            AsyncMock(return_value=1536),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.to_response",
            return_value=self._embedding_payload(created),
        ), patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.routes.embeddings.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
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
        self.assertEqual(user_model.embedding_id, current_embedding_id)
        mocked_publish.assert_not_awaited()

    def test_models_route_not_shadowed_by_embedding_id_route(self):
        connector = self._connector_obj()
        runtime_cls = types.SimpleNamespace(
            supported_connector_types=lambda: ["openai"],
            fetch_available_models=AsyncMock(
                return_value=[{"id": "text-embedding-3-small", "name": "text-embedding-3-small"}]
            )
        )

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_by_type",
            return_value=runtime_cls,
        ):
            response = self.client.get(
                f"/embeddings/models/{connector.id}",
                params={"embedding_type": "openai"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "text-embedding-3-small")

    def test_get_models_allows_read_access_to_foreign_connector(self):
        connector = self._connector_obj()
        connector.owner_id = uuid.uuid4()
        runtime_cls = types.SimpleNamespace(
            supported_connector_types=lambda: ["openai"],
            fetch_available_models=AsyncMock(
                return_value=[{"id": "text-embedding-3-small", "name": "text-embedding-3-small"}]
            ),
        )

        with patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_by_type",
            return_value=runtime_cls,
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id_with_access_for_user",
            AsyncMock(return_value=(connector, True, False)),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ):
            response = self.client.get(
                f"/embeddings/models/{connector.id}",
                params={"embedding_type": "openai"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "text-embedding-3-small")

    def test_fetch_models_for_unsaved_connector(self):
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "EmbeddingsGigaR", "name": "EmbeddingsGigaR"}]
            )
        )

        with patch(
            "giga_agent.routes.embeddings.validate_connector_settings_or_422",
            AsyncMock(return_value={"gigachat_credentials": "token"}),
        ), patch(
            "giga_agent.routes.embeddings._validate_embedding_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_by_type",
            return_value=runtime_cls,
        ):
            response = self.client.post(
                "/embeddings/models/",
                json={
                    "embedding_type": "gigachat",
                    "connector_type": "gigachat",
                    "settings": {"gigachat_credentials": "token"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "EmbeddingsGigaR")

    def test_get_models_returns_422_for_unknown_embedding_type(self):
        connector = self._connector_obj()

        with patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ):
            response = self.client.get(
                f"/embeddings/models/{connector.id}",
                params={"embedding_type": "unknown-runtime"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Unknown embedding type", response.json()["detail"])

    def test_get_models_returns_422_for_incompatible_embedding_and_connector(self):
        connector = self._connector_obj(connector_type="openai")
        runtime_cls = types.SimpleNamespace(supported_connector_types=lambda: ["openai"])

        with patch(
            "giga_agent.routes.embeddings._resolve_embedding_runtime_by_type",
            return_value=runtime_cls,
        ), patch(
            "giga_agent.routes.embeddings._validate_connector_link",
            AsyncMock(return_value=connector.id),
        ), patch(
            "giga_agent.routes.embeddings.ConnectorRepository.get_by_id",
            AsyncMock(return_value=connector),
        ):
            response = self.client.get(
                f"/embeddings/models/{connector.id}",
                params={"embedding_type": "gigachat"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("not compatible", response.json()["detail"])

    def test_deactivate_current_auto_clears_current(self):
        self.skipTest("Редактирование эмбеддингов отключено")

    def test_patch_settings_uses_current_embedding_type(self):
        self.skipTest("Редактирование эмбеддингов отключено")

    def test_delete_current_auto_clears_current(self):
        embedding_id = uuid.uuid4()
        existing = self._embedding_obj(embedding_id=embedding_id)
        user_model = types.SimpleNamespace(embedding_id=embedding_id)

        with patch(
            "giga_agent.routes.embeddings.get_user_model",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.routes.embeddings._get_embedding_with_write_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.embeddings.EmbeddingRepository.delete",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.embeddings.clear_user_current_link_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current, patch(
            "giga_agent.routes.embeddings.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
            response = self.client.delete(f"/embeddings/{embedding_id}")

        self.assertEqual(response.status_code, 204)
        mocked_clear_current.assert_awaited_once()
        mocked_publish.assert_awaited_once()
        event = mocked_publish.await_args.args[0]
        self.assertIsInstance(event, UserEmbeddingChangedEvent)
        self.assertEqual(event.user_id, self.user.id)
        self.assertEqual(event.old_embedding_id, embedding_id)
        self.assertIsNone(event.new_embedding_id)
