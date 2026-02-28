import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.search_engines import _validate_connector_link, router


class SearchGeneratorsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            is_superuser=True,
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

    def _engine_obj(
        self,
        *,
        engine_id: uuid.UUID | None = None,
        engine_type: str = "tavily",
        owner_id: uuid.UUID | None = None,
        settings: dict | None = None,
        connector_id: uuid.UUID | None = None,
        is_active: bool = True,
    ):
        return types.SimpleNamespace(
            id=engine_id or uuid.uuid4(),
            owner_id=owner_id or self.user.id,
            type=engine_type,
            name="engine",
            settings=settings or {"search_depth": "basic"},
            connector_id=connector_id,
            is_active=is_active,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _response_payload(self, engine_obj) -> dict:
        return {
            "id": str(engine_obj.id),
            "owner_id": str(engine_obj.owner_id),
            "type": engine_obj.type,
            "name": engine_obj.name,
            "settings": engine_obj.settings,
            "connector_id": (
                str(engine_obj.connector_id)
                if engine_obj.connector_id is not None
                else None
            ),
            "is_active": engine_obj.is_active,
            "created_at": engine_obj.created_at,
            "updated_at": engine_obj.updated_at,
        }

    def test_create_success(self):
        created = self._engine_obj(connector_id=None)

        with patch(
            "giga_agent.routes.search_engines._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ), patch(
            "giga_agent.routes.search_engines._validate_settings",
            AsyncMock(return_value={"search_depth": "basic"}),
        ), patch(
            "giga_agent.routes.search_engines._validate_connector_link",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.to_response",
            return_value=self._response_payload(created),
        ):
            response = self.client.post(
                "/search-engines",
                json={
                    "type": "tavily",
                    "name": "Tavily",
                    "settings": {"search_depth": "basic"},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "tavily")

    def test_create_engine_with_permissions_for_superuser(self):
        created = self._engine_obj(connector_id=None)

        with patch(
            "giga_agent.routes.search_engines._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ), patch(
            "giga_agent.routes.search_engines._validate_settings",
            AsyncMock(return_value={"search_depth": "basic"}),
        ), patch(
            "giga_agent.routes.search_engines._validate_connector_link",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.search_engines.ResourcePermissionRepository.set_read_acl",
            AsyncMock(return_value=None),
        ) as mocked_set_acl, patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.to_response",
            return_value=self._response_payload(created),
        ):
            response = self.client.post(
                "/search-engines",
                json={
                    "type": "tavily",
                    "settings": {"search_depth": "basic"},
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

    def test_create_engine_with_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False

        with patch(
            "giga_agent.routes.search_engines._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ) as mocked_resolve_runtime:
            response = self.client.post(
                "/search-engines",
                json={
                    "type": "tavily",
                    "settings": {"search_depth": "basic"},
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [],
                        "public_read": False,
                    },
                },
            )

        self.assertEqual(response.status_code, 403)
        mocked_resolve_runtime.assert_not_called()

    def test_get_engine_types_meta(self):
        with patch(
            "giga_agent.routes.search_engines.SearchEngineRegistry.available_types",
            return_value=["tavily"],
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRegistry.get",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ):
            response = self.client.get("/search-engines/types/meta")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "type": "tavily",
                    "supported_connector_types": ["tavily"],
                    "requires_connector": False,
                }
            ],
        )

    def test_patch_with_type_returns_422(self):
        response = self.client.patch(
            f"/search-engines/{uuid.uuid4()}",
            json={"type": "another"},
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_settings_uses_current_engine_type(self):
        engine_id = uuid.uuid4()
        existing = self._engine_obj(
            engine_id=engine_id,
            connector_id=uuid.uuid4(),
            settings={"search_depth": "basic"},
        )
        updated = self._engine_obj(
            engine_id=engine_id,
            connector_id=existing.connector_id,
            settings={"search_depth": "advanced"},
        )

        with patch(
            "giga_agent.routes.search_engines._get_engine_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.search_engines._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ), patch(
            "giga_agent.routes.search_engines._validate_settings",
            AsyncMock(return_value={"search_depth": "advanced"}),
        ) as mocked_validate_settings, patch(
            "giga_agent.routes.search_engines._validate_connector_link",
            AsyncMock(return_value=existing.connector_id),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.to_response",
            return_value=self._response_payload(updated),
        ):
            response = self.client.patch(
                f"/search-engines/{engine_id}",
                json={"settings": {"search_depth": "advanced"}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_settings.assert_awaited_once_with(
            "tavily", {"search_depth": "advanced"}
        )

    def test_deactivate_current_auto_clears_current(self):
        engine_id = uuid.uuid4()
        existing = self._engine_obj(engine_id=engine_id, connector_id=uuid.uuid4(), is_active=True)
        updated = self._engine_obj(engine_id=engine_id, connector_id=existing.connector_id, is_active=False)

        with patch(
            "giga_agent.routes.search_engines._get_engine_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.search_engines._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["tavily"]),
        ), patch(
            "giga_agent.routes.search_engines._validate_connector_link",
            AsyncMock(return_value=existing.connector_id),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.search_engines._clear_current_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current, patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.to_response",
            return_value=self._response_payload(updated),
        ):
            response = self.client.patch(
                f"/search-engines/{engine_id}",
                json={"is_active": False},
            )

        self.assertEqual(response.status_code, 200)
        mocked_clear_current.assert_awaited_once()

    def test_delete_current_auto_clears_current(self):
        engine_id = uuid.uuid4()
        existing = self._engine_obj(engine_id=engine_id)

        with patch(
            "giga_agent.routes.search_engines._get_engine_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.search_engines.SearchEngineRepository.delete",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.search_engines._clear_current_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current:
            response = self.client.delete(f"/search-engines/{engine_id}")

        self.assertEqual(response.status_code, 204)
        mocked_clear_current.assert_awaited_once()

    def test_owner_check_returns_403(self):
        engine_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.search_engines._get_engine_with_read_check",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="Access denied",
                )
            ),
        ):
            response = self.client.get(f"/search-engines/{engine_id}")

        self.assertEqual(response.status_code, 403)

    def test_not_found_returns_404(self):
        engine_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.search_engines._get_engine_with_read_check",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=404,
                    detail="Search engine not found",
                )
            ),
        ):
            response = self.client.get(f"/search-engines/{engine_id}")

        self.assertEqual(response.status_code, 404)


class SearchEnginesConnectorValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_connector_link_allows_missing_connector_for_supported_type(self):
        connector_repo = types.SimpleNamespace(get_by_id=AsyncMock())
        owner_id = uuid.uuid4()

        result = await _validate_connector_link(
            owner_id=owner_id,
            connector_id=None,
            supported_connector_types=["tavily"],
            connector_repo=connector_repo,
        )

        self.assertIsNone(result)
        connector_repo.get_by_id.assert_not_called()

    async def test_validate_connector_link_rejects_unsupported_connector_type(self):
        owner_id = uuid.uuid4()
        connector_id = uuid.uuid4()
        connector_repo = types.SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=types.SimpleNamespace(
                    id=connector_id,
                    owner_id=owner_id,
                    is_active=True,
                    type="openai",
                )
            )
        )

        with self.assertRaises(HTTPException) as ctx:
            await _validate_connector_link(
                owner_id=owner_id,
                connector_id=connector_id,
                supported_connector_types=["tavily"],
                connector_repo=connector_repo,
            )

        self.assertEqual(ctx.exception.status_code, 422)
