import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.connectors import router


class ConnectorsRouterTests(unittest.TestCase):
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
        owner_id: uuid.UUID | None = None,
        settings: dict | None = None,
        is_active: bool = True,
    ):
        return types.SimpleNamespace(
            id=connector_id or uuid.uuid4(),
            owner_id=owner_id or self.user.id,
            type=connector_type,
            name="conn",
            settings=settings or {"api_key": "sk-test"},
            is_active=is_active,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _response_payload(self, connector_obj) -> dict:
        return {
            "id": str(connector_obj.id),
            "owner_id": str(connector_obj.owner_id),
            "type": connector_obj.type,
            "name": connector_obj.name,
            "settings": connector_obj.settings,
            "is_active": connector_obj.is_active,
            "created_at": connector_obj.created_at,
            "updated_at": connector_obj.updated_at,
        }

    def test_create_connector_success(self):
        created = self._connector_obj()
        with patch(
            "giga_agent.routes.connectors._resolve_runtime_cls",
            return_value=object(),
        ), patch(
            "giga_agent.routes.connectors._validate_settings",
            AsyncMock(return_value={"api_key": "sk-test"}),
        ), patch(
            "giga_agent.routes.connectors.ConnectorRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.connectors.ConnectorRepository.to_response",
            return_value=self._response_payload(created),
        ):
            response = self.client.post(
                "/connectors",
                json={
                    "type": "openai",
                    "name": "OpenAI Conn",
                    "settings": {"api_key": "sk-test"},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "openai")

    def test_get_connectors_success(self):
        connector = self._connector_obj()
        with patch(
            "giga_agent.routes.connectors.ConnectorRepository.get_by_owner",
            AsyncMock(return_value=[connector]),
        ), patch(
            "giga_agent.routes.connectors.ConnectorRepository.to_response",
            return_value=self._response_payload(connector),
        ):
            response = self.client.get("/connectors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], str(connector.id))

    def test_patch_type_change_checks_dependencies(self):
        connector_id = uuid.uuid4()
        existing = self._connector_obj(connector_id=connector_id, connector_type="openai")
        updated = self._connector_obj(connector_id=connector_id, connector_type="gigachat")

        with patch(
            "giga_agent.routes.connectors._get_connector_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.connectors._resolve_runtime_cls",
            return_value=object(),
        ), patch(
            "giga_agent.routes.connectors._validate_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.connectors._validate_type_change_compatibility",
            AsyncMock(return_value=None),
        ) as mocked_validate_compat, patch(
            "giga_agent.routes.connectors.ConnectorRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.connectors.ConnectorRepository.to_response",
            return_value=self._response_payload(updated),
        ), patch(
            "giga_agent.routes.connectors.cache.delete_tags",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                f"/connectors/{connector_id}",
                json={"type": "gigachat", "settings": {}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_compat.assert_awaited_once()
        self.assertEqual(response.json()["type"], "gigachat")

    def test_delete_connector_invalidates_dependent_caches(self):
        connector = self._connector_obj()
        llm = types.SimpleNamespace(id=uuid.uuid4())
        generator = types.SimpleNamespace(id=uuid.uuid4())
        engine = types.SimpleNamespace(id=uuid.uuid4())

        with patch(
            "giga_agent.routes.connectors._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.connectors.LLMRepository.get_by_connector",
            AsyncMock(return_value=[llm]),
        ), patch(
            "giga_agent.routes.connectors.ImageGeneratorRepository.get_by_connector",
            AsyncMock(return_value=[generator]),
        ), patch(
            "giga_agent.routes.connectors.SearchEngineRepository.get_by_connector",
            AsyncMock(return_value=[engine]),
        ), patch(
            "giga_agent.routes.connectors.LLMRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_llm_invalidate, patch(
            "giga_agent.routes.connectors.ImageGeneratorRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_gen_invalidate, patch(
            "giga_agent.routes.connectors.SearchEngineRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_engine_invalidate, patch(
            "giga_agent.routes.connectors.ConnectorRepository.delete",
            AsyncMock(return_value=None),
        ) as mocked_delete, patch(
            "giga_agent.routes.connectors.cache.delete_tags",
            AsyncMock(return_value=None),
        ) as mocked_delete_tags:
            response = self.client.delete(f"/connectors/{connector.id}")

        self.assertEqual(response.status_code, 204)
        mocked_llm_invalidate.assert_awaited_once_with(llm.id)
        mocked_gen_invalidate.assert_awaited_once_with(generator.id)
        mocked_engine_invalidate.assert_awaited_once_with(engine.id)
        mocked_delete.assert_awaited_once()
        mocked_delete_tags.assert_awaited_once()
