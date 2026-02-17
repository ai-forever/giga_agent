import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.llms import router


class LLMsRouterTests(unittest.TestCase):
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

    def _llm_obj(
        self,
        *,
        llm_id: uuid.UUID | None = None,
        connector_id: uuid.UUID | None = None,
        llm_type: str = "openai",
    ):
        return types.SimpleNamespace(
            id=llm_id or uuid.uuid4(),
            owner_id=self.user.id,
            connector_id=connector_id or uuid.uuid4(),
            type=llm_type,
            model_id="gpt-4o-mini",
            name="main",
            parallel_calls=1,
            settings={},
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _llm_payload(self, llm_obj) -> dict:
        return {
            "id": str(llm_obj.id),
            "owner_id": str(llm_obj.owner_id),
            "type": llm_obj.type,
            "connector_id": str(llm_obj.connector_id),
            "model_id": llm_obj.model_id,
            "name": llm_obj.name,
            "parallel_calls": llm_obj.parallel_calls,
            "settings": llm_obj.settings,
            "is_active": llm_obj.is_active,
            "created_at": llm_obj.created_at,
            "updated_at": llm_obj.updated_at,
        }

    def test_create_llm_success(self):
        connector = self._connector_obj()
        created = self._llm_obj(connector_id=connector.id)

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms.LLMRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.llms.LLMRepository.to_response",
            return_value=self._llm_payload(created),
        ), patch(
            "giga_agent.routes.llms.cache.delete_tags",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/llms",
                json={
                    "type": "openai",
                    "connector_id": str(connector.id),
                    "model_id": "gpt-4o-mini",
                    "settings": {},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "openai")
        self.assertEqual(response.json()["connector_id"], str(connector.id))

    def test_models_route_not_shadowed_by_llm_id_route(self):
        connector = self._connector_obj()
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "gpt-4o-mini", "name": "gpt-4o-mini"}]
            )
        )

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime_for_connector",
            return_value=runtime_cls,
        ):
            response = self.client.get(f"/llms/models/{connector.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "gpt-4o-mini")

    def test_fetch_models_for_unsaved_connector(self):
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "gpt-4o", "name": "gpt-4o"}]
            )
        )
        with patch(
            "giga_agent.routes.llms._validate_connector_settings",
            AsyncMock(return_value={"api_key": "sk-test"}),
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime_for_connector",
            return_value=runtime_cls,
        ):
            response = self.client.post(
                "/llms/models/",
                json={"connector_type": "openai", "settings": {"api_key": "sk-test"}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "gpt-4o")

    def test_patch_llm_updates_connector_and_invalidates_tags(self):
        llm_id = uuid.uuid4()
        old_connector_id = uuid.uuid4()
        new_connector_id = uuid.uuid4()
        existing = self._llm_obj(
            llm_id=llm_id,
            connector_id=old_connector_id,
            llm_type="openai",
        )
        updated = self._llm_obj(
            llm_id=llm_id,
            connector_id=new_connector_id,
            llm_type="openai",
        )
        connector = self._connector_obj(connector_id=new_connector_id, connector_type="openai")

        with patch(
            "giga_agent.routes.llms._get_llm_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms.LLMRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.llms.LLMRepository.to_response",
            return_value=self._llm_payload(updated),
        ), patch(
            "giga_agent.routes.llms.cache.delete_tags",
            AsyncMock(return_value=None),
        ) as mocked_delete_tags:
            response = self.client.patch(
                f"/llms/{llm_id}",
                json={"connector_id": str(new_connector_id)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["connector_id"], str(new_connector_id))
        self.assertEqual(mocked_delete_tags.await_count, 2)
