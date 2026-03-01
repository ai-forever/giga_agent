import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.sandboxes import router


class SandboxesRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            is_superuser=True,
        )
        self.db = types.SimpleNamespace(get=AsyncMock(), commit=AsyncMock())
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield self.db

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    def _provider_obj(self, *, provider_id: uuid.UUID | None = None):
        return types.SimpleNamespace(
            id=provider_id or uuid.uuid4(),
            owner_id=self.user.id,
            type="e2b",
            name="main",
            settings={},
            idle_timeout=3600,
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _provider_payload(self, provider_obj) -> dict:
        return {
            "id": str(provider_obj.id),
            "owner_id": str(provider_obj.owner_id),
            "type": provider_obj.type,
            "name": provider_obj.name,
            "settings": provider_obj.settings,
            "idle_timeout": provider_obj.idle_timeout,
            "is_active": provider_obj.is_active,
            "created_at": provider_obj.created_at,
            "updated_at": provider_obj.updated_at,
        }

    def test_create_first_provider_auto_sets_user_sandbox_provider_id(self):
        provider = self._provider_obj()
        user_model = types.SimpleNamespace(sandbox_provider_id=None)
        self.db.get = AsyncMock(return_value=user_model)

        with patch(
            "giga_agent.routes.sandboxes.validate_provider_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.create",
            AsyncMock(return_value=provider),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.to_response",
            return_value=self._provider_payload(provider),
        ), patch(
            "giga_agent.routes.sandboxes.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_invalidate_cache, patch(
            "giga_agent.routes.sandboxes.cache.delete_match",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/sandboxes/providers",
                json={
                    "type": "e2b",
                    "name": "main",
                    "settings": {},
                    "idle_timeout": 3600,
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(user_model.sandbox_provider_id, provider.id)
        self.db.commit.assert_awaited()
        mocked_invalidate_cache.assert_awaited_once_with(self.user.id)

    def test_create_provider_with_permissions_for_superuser(self):
        provider = self._provider_obj()
        user_model = types.SimpleNamespace(sandbox_provider_id=None)
        self.db.get = AsyncMock(return_value=user_model)

        with patch(
            "giga_agent.routes.sandboxes.validate_provider_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.create",
            AsyncMock(return_value=provider),
        ), patch(
            "giga_agent.routes.sandboxes.ResourcePermissionRepository.set_read_acl",
            AsyncMock(return_value=None),
        ) as mocked_set_acl, patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.to_response",
            return_value=self._provider_payload(provider),
        ), patch(
            "giga_agent.routes.sandboxes.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.sandboxes.cache.delete_match",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/sandboxes/providers",
                json={
                    "type": "e2b",
                    "name": "main",
                    "settings": {},
                    "idle_timeout": 3600,
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [str(uuid.uuid4())],
                        "public_read": False,
                    },
                },
            )

        self.assertEqual(response.status_code, 201)
        mocked_set_acl.assert_awaited_once()

    def test_create_provider_with_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        with patch(
            "giga_agent.routes.sandboxes.validate_provider_settings",
            AsyncMock(return_value={}),
        ) as mocked_validate_settings:
            response = self.client.post(
                "/sandboxes/providers",
                json={
                    "type": "e2b",
                    "name": "main",
                    "settings": {},
                    "idle_timeout": 3600,
                    "is_active": True,
                    "permissions": {
                        "read_user_ids": [str(uuid.uuid4())],
                        "read_group_ids": [],
                        "public_read": False,
                    },
                },
            )

        self.assertEqual(response.status_code, 403)
        mocked_validate_settings.assert_not_awaited()

    def test_get_providers_includes_can_edit(self):
        owned = self._provider_obj()
        writable = self._provider_obj(provider_id=uuid.uuid4())
        writable.owner_id = uuid.uuid4()
        readonly = self._provider_obj(provider_id=uuid.uuid4())
        readonly.owner_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.list_readable_with_edit_for_user",
            AsyncMock(return_value=[(owned, True), (writable, True), (readonly, False)]),
        ):
            response = self.client.get("/sandboxes/providers")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        can_edit_by_id = {item["id"]: item["can_edit"] for item in payload}
        self.assertTrue(can_edit_by_id[str(owned.id)])
        self.assertTrue(can_edit_by_id[str(writable.id)])
        self.assertFalse(can_edit_by_id[str(readonly.id)])

    def test_create_next_provider_does_not_change_user_sandbox_provider_id(self):
        provider = self._provider_obj()
        current_provider_id = uuid.uuid4()
        user_model = types.SimpleNamespace(sandbox_provider_id=current_provider_id)
        self.db.get = AsyncMock(return_value=user_model)

        with patch(
            "giga_agent.routes.sandboxes.validate_provider_settings",
            AsyncMock(return_value={}),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.create",
            AsyncMock(return_value=provider),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.to_response",
            return_value=self._provider_payload(provider),
        ), patch(
            "giga_agent.routes.sandboxes.cache.delete_match",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/sandboxes/providers",
                json={
                    "type": "e2b",
                    "name": "next",
                    "settings": {},
                    "idle_timeout": 3600,
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(user_model.sandbox_provider_id, current_provider_id)

    def test_delete_active_provider_resets_user_sandbox_provider_id(self):
        provider = self._provider_obj()
        user_model = types.SimpleNamespace(sandbox_provider_id=provider.id)
        self.db.get = AsyncMock(return_value=user_model)

        with patch(
            "giga_agent.routes.sandboxes.get_provider_with_write_check",
            AsyncMock(return_value=provider),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxProviderRepository.delete",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.sandboxes.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_invalidate_cache, patch(
            "giga_agent.routes.sandboxes.cache.delete_match",
            AsyncMock(return_value=None),
        ):
            response = self.client.delete(f"/sandboxes/providers/{provider.id}")

        self.assertEqual(response.status_code, 204)
        self.assertIsNone(user_model.sandbox_provider_id)
        self.db.commit.assert_awaited()
        mocked_invalidate_cache.assert_awaited_once_with(self.user.id)
