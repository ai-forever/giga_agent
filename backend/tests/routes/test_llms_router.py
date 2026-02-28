import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
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
        connector_runtime = types.SimpleNamespace()
        created = self._llm_obj(connector_id=connector.id)
        mocked_check = AsyncMock(return_value=None)

        class _RuntimeStub:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            @classmethod
            async def validate_settings(cls, settings: dict) -> dict:
                return settings

            async def check_connection(self):
                return await mocked_check()

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.routes.llms.ConnectorRegistry.get_runtime",
            AsyncMock(return_value=connector_runtime),
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
        mocked_check.assert_awaited_once()

    def test_create_llm_returns_422_when_connection_check_fails(self):
        connector = self._connector_obj()
        connector_runtime = types.SimpleNamespace()

        class _RuntimeStub:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            @classmethod
            async def validate_settings(cls, settings: dict) -> dict:
                return settings

            async def check_connection(self):
                raise RuntimeError("auth failed")

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.routes.llms.ConnectorRegistry.get_runtime",
            AsyncMock(return_value=connector_runtime),
        ), patch(
            "giga_agent.routes.llms.LLMRepository.create",
            AsyncMock(),
        ) as mocked_create:
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

        self.assertEqual(response.status_code, 422)
        self.assertIn("LLM connection check failed", response.json()["detail"])
        mocked_create.assert_not_awaited()

    def test_models_route_not_shadowed_by_llm_id_route(self):
        connector = self._connector_obj()
        connector_runtime = types.SimpleNamespace()
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "gpt-4o-mini", "name": "gpt-4o-mini"}]
            )
        )

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime_by_type",
            return_value=runtime_cls,
        ), patch(
            "giga_agent.routes.llms.ConnectorRegistry.get_runtime",
            AsyncMock(return_value=connector_runtime),
        ):
            response = self.client.get(
                f"/llms/models/{connector.id}",
                params={"llm_type": "openai"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "gpt-4o-mini")

    def test_fetch_models_for_unsaved_connector(self):
        connector_runtime = types.SimpleNamespace()
        runtime_cls = types.SimpleNamespace(
            fetch_available_models=AsyncMock(
                return_value=[{"id": "gpt-4o", "name": "gpt-4o"}]
            )
        )
        with patch(
            "giga_agent.routes.llms._validate_connector_settings",
            AsyncMock(return_value={"api_key": "sk-test"}),
        ), patch(
            "giga_agent.routes.llms._validate_llm_connector_compatibility",
            return_value=None,
        ), patch(
            "giga_agent.routes.llms._resolve_llm_runtime_by_type",
            return_value=runtime_cls,
        ), patch(
            "giga_agent.routes.llms.ConnectorRegistry.get_runtime",
            AsyncMock(return_value=connector_runtime),
        ):
            response = self.client.post(
                "/llms/models/",
                json={
                    "llm_type": "openai",
                    "connector_type": "openai",
                    "settings": {"api_key": "sk-test"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "gpt-4o")

    def test_get_models_returns_422_for_unknown_llm_type(self):
        connector = self._connector_obj()

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ):
            response = self.client.get(
                f"/llms/models/{connector.id}",
                params={"llm_type": "unknown-runtime"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Unknown llm type", response.json()["detail"])

    def test_get_models_returns_422_for_incompatible_llm_and_connector(self):
        connector = self._connector_obj(connector_type="openai")

        with patch(
            "giga_agent.routes.llms._get_connector_with_owner_check",
            AsyncMock(return_value=connector),
        ):
            response = self.client.get(
                f"/llms/models/{connector.id}",
                params={"llm_type": "gigachat"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("not compatible", response.json()["detail"])

    def test_get_llms_uses_readable_scope(self):
        readable = [self._llm_obj(), self._llm_obj()]
        payload = [self._llm_payload(item) for item in readable]

        with patch(
            "giga_agent.routes.llms.LLMRepository.get_readable_for_user",
            AsyncMock(return_value=readable),
        ) as mocked_get, patch(
            "giga_agent.routes.llms.LLMRepository.to_response",
            side_effect=payload,
        ):
            response = self.client.get("/llms")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(mocked_get.await_args.args[0], self.user.id)

    def test_get_llm_uses_read_check(self):
        llm = self._llm_obj()
        with patch(
            "giga_agent.routes.llms._get_llm_with_read_check",
            AsyncMock(return_value=llm),
        ) as mocked_get, patch(
            "giga_agent.routes.llms.LLMRepository.to_response",
            return_value=self._llm_payload(llm),
        ):
            response = self.client.get(f"/llms/{llm.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(llm.id))
        self.assertEqual(mocked_get.await_args.kwargs["user_id"], self.user.id)

    def test_get_llm_returns_403_when_no_read_access(self):
        llm_id = uuid.uuid4()
        with patch(
            "giga_agent.routes.llms._get_llm_with_read_check",
            AsyncMock(side_effect=HTTPException(status_code=403, detail="Access denied")),
        ):
            response = self.client.get(f"/llms/{llm_id}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access denied")

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
