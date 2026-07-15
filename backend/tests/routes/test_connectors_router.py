import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from gigachat.settings import AUTH_URL as GIGACHAT_DEFAULT_AUTH_URL
from gigachat.settings import BASE_URL as GIGACHAT_DEFAULT_BASE_URL

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.connectors import _validate_type_change_compatibility, router


class ConnectorsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(), is_active=True, is_superuser=True
        )
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
        with (
            patch(
                "giga_agent.routes.connectors._resolve_runtime_cls",
                return_value=object(),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ) as mocked_check,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(created),
            ),
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
        mocked_check.assert_awaited_once()

    def test_get_connector_settings_schema_materializes_default_factory(self):
        class _SchemaStub(BaseModel):
            base_url: str = Field(default_factory=lambda: "https://api.example.com")

        class _RuntimeStub:
            @classmethod
            def settings_schema(cls):
                return _SchemaStub

        with patch(
            "giga_agent.routes.connectors._resolve_runtime_cls",
            return_value=_RuntimeStub,
        ):
            response = self.client.get("/connectors/types/openai/settings-schema")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["properties"]["base_url"]["default"],
            "https://api.example.com",
        )

    def test_get_gigachat_settings_schema_exposes_default_urls(self):
        response = self.client.get("/connectors/types/gigachat/settings-schema")

        self.assertEqual(response.status_code, 200)
        properties = response.json()["properties"]
        self.assertEqual(
            properties["gigachat_base_url"]["default"],
            GIGACHAT_DEFAULT_BASE_URL,
        )
        self.assertEqual(
            properties["gigachat_auth_url"]["default"],
            GIGACHAT_DEFAULT_AUTH_URL,
        )

    def test_create_connector_skips_connection_check_when_disabled(self):
        created = self._connector_obj()
        with (
            patch(
                "giga_agent.routes.connectors._resolve_runtime_cls",
                return_value=object(),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ) as mocked_check,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/connectors",
                json={
                    "type": "openai",
                    "name": "OpenAI Conn",
                    "settings": {"api_key": "sk-test"},
                    "is_active": True,
                    "check_connection": False,
                },
            )

        self.assertEqual(response.status_code, 201)
        mocked_check.assert_not_awaited()

    def test_create_connector_with_permissions_for_superuser(self):
        created = self._connector_obj()
        with (
            patch(
                "giga_agent.routes.connectors._resolve_runtime_cls",
                return_value=object(),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.connectors.ResourcePermissionRepository.set_read_acl",
                AsyncMock(return_value=None),
            ) as mocked_set_acl,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/connectors",
                json={
                    "type": "openai",
                    "settings": {"api_key": "sk-test"},
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

    def test_create_connector_with_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        with (
            patch(
                "giga_agent.routes.connectors._resolve_runtime_cls",
                return_value=object(),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.create",
                AsyncMock(),
            ) as mocked_create,
        ):
            response = self.client.post(
                "/connectors",
                json={
                    "type": "openai",
                    "settings": {"api_key": "sk-test"},
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [],
                        "public_read": False,
                    },
                },
            )

        self.assertEqual(response.status_code, 403)
        mocked_create.assert_not_awaited()

    def test_create_connector_returns_422_when_connection_check_fails(self):
        with (
            patch(
                "giga_agent.routes.connectors._resolve_runtime_cls",
                return_value=object(),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(
                    side_effect=HTTPException(
                        status_code=422,
                        detail="Connector connection check failed: auth failed",
                    )
                ),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.create",
                AsyncMock(),
            ) as mocked_create,
        ):
            response = self.client.post(
                "/connectors",
                json={
                    "type": "openai",
                    "settings": {"api_key": "sk-test"},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Connector connection check failed", response.json()["detail"])
        mocked_create.assert_not_awaited()

    def test_get_connectors_success(self):
        connector = self._connector_obj()
        with (
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.list_readable_with_edit_for_user",
                AsyncMock(return_value=[(connector, True)]),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(connector),
            ),
        ):
            response = self.client.get("/connectors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], str(connector.id))

    def test_get_connectors_includes_can_edit(self):
        owner_connector = self._connector_obj()
        writable_connector = self._connector_obj(owner_id=uuid.uuid4())
        readonly_connector = self._connector_obj(owner_id=uuid.uuid4())

        with patch(
            "giga_agent.routes.connectors.ConnectorRepository.list_readable_with_edit_for_user",
            AsyncMock(
                return_value=[
                    (owner_connector, True),
                    (writable_connector, True),
                    (readonly_connector, False),
                ]
            ),
        ):
            response = self.client.get("/connectors")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        can_edit_by_id = {item["id"]: item["can_edit"] for item in payload}
        self.assertTrue(can_edit_by_id[str(owner_connector.id)])
        self.assertTrue(can_edit_by_id[str(writable_connector.id)])
        self.assertFalse(can_edit_by_id[str(readonly_connector.id)])

    def test_patch_rejects_unknown_type_field(self):
        connector_id = uuid.uuid4()
        response = self.client.patch(
            f"/connectors/{connector_id}",
            json={"type": "gigachat", "settings": {}},
        )

        self.assertEqual(response.status_code, 422)

    def test_patch_with_settings_skips_connection_check_when_disabled(self):
        connector_id = uuid.uuid4()
        existing = self._connector_obj(
            connector_id=connector_id, connector_type="openai"
        )
        updated = self._connector_obj(
            connector_id=connector_id, connector_type="openai"
        )

        with (
            patch(
                "giga_agent.routes.connectors._get_connector_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.connectors._validate_settings",
                AsyncMock(return_value={"api_key": "sk-test"}),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ) as mocked_check,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.update",
                AsyncMock(return_value=updated),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/connectors/{connector_id}",
                json={"settings": {"api_key": "sk-test"}, "check_connection": False},
            )

        self.assertEqual(response.status_code, 200)
        mocked_check.assert_not_awaited()

    def test_patch_without_settings_does_not_run_connection_check(self):
        connector_id = uuid.uuid4()
        existing = self._connector_obj(
            connector_id=connector_id, connector_type="openai"
        )
        updated = self._connector_obj(
            connector_id=connector_id, connector_type="openai"
        )

        with (
            patch(
                "giga_agent.routes.connectors._get_connector_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.connectors._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ) as mocked_check,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.update",
                AsyncMock(return_value=updated),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/connectors/{connector_id}",
                json={"name": "renamed"},
            )

        self.assertEqual(response.status_code, 200)
        mocked_check.assert_not_awaited()

    def test_delete_connector_success(self):
        connector = self._connector_obj()

        with (
            patch(
                "giga_agent.routes.connectors._get_connector_with_write_check",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.delete",
                AsyncMock(return_value=None),
            ) as mocked_delete,
        ):
            response = self.client.delete(f"/connectors/{connector.id}")

        self.assertEqual(response.status_code, 204)
        mocked_delete.assert_awaited_once()

    def test_patch_connector_allows_null_name(self):
        connector = self._connector_obj()
        updated = self._connector_obj(connector_id=connector.id)
        updated.name = None

        with (
            patch(
                "giga_agent.routes.connectors._get_connector_with_write_check",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.update",
                AsyncMock(return_value=updated),
            ) as mocked_update,
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/connectors/{connector.id}",
                json={"name": None, "check_connection": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["name"])
        self.assertIsNone(mocked_update.await_args.kwargs["name"])

    def test_patch_connector_rejects_null_is_active(self):
        connector = self._connector_obj()

        with (
            patch(
                "giga_agent.routes.connectors._get_connector_with_write_check",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.routes.connectors.ConnectorRepository.update",
                AsyncMock(),
            ) as mocked_update,
        ):
            response = self.client.patch(
                f"/connectors/{connector.id}",
                json={"is_active": None},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "is_active must not be null when provided",
        )
        mocked_update.assert_not_awaited()

    def test_patch_connector_rejects_unknown_fields(self):
        response = self.client.patch(
            f"/connectors/{uuid.uuid4()}",
            json={"unknown_field": "value"},
        )

        self.assertEqual(response.status_code, 422)


class ConnectorCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_type_change_checks_embedding_dependency(self):
        connector_id = uuid.uuid4()
        embedding = types.SimpleNamespace(id=uuid.uuid4(), type="openai")

        class _EmbeddingRuntime:
            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return False

            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

        llm_repo = types.SimpleNamespace(get_by_connector=AsyncMock(return_value=[]))
        embedding_repo = types.SimpleNamespace(
            get_by_connector=AsyncMock(return_value=[embedding])
        )
        image_repo = types.SimpleNamespace(get_by_connector=AsyncMock(return_value=[]))
        search_repo = types.SimpleNamespace(get_by_connector=AsyncMock(return_value=[]))

        with patch(
            "giga_agent.routes.connectors.EmbeddingRegistry.get",
            return_value=_EmbeddingRuntime,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await _validate_type_change_compatibility(
                    connector_id=connector_id,
                    connector_type="gigachat",
                    llm_repo=llm_repo,
                    embedding_repo=embedding_repo,
                    image_repo=image_repo,
                    search_repo=search_repo,
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("embedding", str(ctx.exception.detail))
