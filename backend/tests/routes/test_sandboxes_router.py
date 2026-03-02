import types
import unittest
import uuid
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.sandboxes import router
from giga_agent.sandbox.manager import SandboxBusyError, StorageOperationError


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

    @contextmanager
    def _patched_env(self, values: dict[str, str], *, clear: bool = False):
        reset_settings_cache()
        with patch.dict(os.environ, values, clear=clear):
            reset_settings_cache()
            try:
                yield
            finally:
                reset_settings_cache()

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

    def _sandbox_obj(
        self,
        *,
        provider_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        sandbox_id: uuid.UUID | None = None,
        status: str = "running",
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ):
        now = datetime.now(timezone.utc)
        return types.SimpleNamespace(
            id=sandbox_id or uuid.uuid4(),
            provider_id=provider_id,
            owner_id=owner_id or self.user.id,
            status=status,
            started_at=started_at or now,
            stopped_at=stopped_at,
        )

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

    def test_get_provider_sandboxes_returns_rows_with_owner_email_and_can_stop(self):
        provider = self._provider_obj()
        own_sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=self.user.id)
        foreign_owner = uuid.uuid4()
        foreign_sandbox = self._sandbox_obj(
            provider_id=provider.id,
            owner_id=foreign_owner,
            status="stopped",
            stopped_at=datetime.now(timezone.utc),
        )

        execute_result = types.SimpleNamespace(
            all=lambda: [
                (self.user.id, "self@example.com"),
                (foreign_owner, "foreign@example.com"),
            ]
        )
        self.db.execute = AsyncMock(return_value=execute_result)

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, False)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider",
            AsyncMock(return_value=[own_sandbox, foreign_sandbox]),
        ):
            response = self.client.get(f"/sandboxes/providers/{provider.id}/sandboxes")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 2)
        row_by_id = {item["id"]: item for item in payload}
        self.assertEqual(row_by_id[str(own_sandbox.id)]["owner_email"], "self@example.com")
        self.assertTrue(row_by_id[str(own_sandbox.id)]["can_stop"])
        self.assertEqual(
            row_by_id[str(foreign_sandbox.id)]["owner_email"],
            "foreign@example.com",
        )
        self.assertFalse(row_by_id[str(foreign_sandbox.id)]["can_stop"])

    def test_get_provider_sandboxes_forbidden_without_read_access(self):
        provider_id = uuid.uuid4()
        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
            ),
        ):
            response = self.client.get(f"/sandboxes/providers/{provider_id}/sandboxes")
        self.assertEqual(response.status_code, 403)

    def test_stop_provider_sandbox_allows_editor_for_any_owner(self):
        provider = self._provider_obj()
        foreign_owner = uuid.uuid4()
        sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=foreign_owner)
        stopped = self._sandbox_obj(
            provider_id=provider.id,
            owner_id=foreign_owner,
            sandbox_id=sandbox.id,
            status="stopped",
            stopped_at=datetime.now(timezone.utc),
        )
        self.db.get = AsyncMock(return_value=types.SimpleNamespace(email="foreign@example.com"))

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, True)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(side_effect=[sandbox, stopped]),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxManager.stop",
            AsyncMock(return_value=stopped),
        ) as mocked_stop:
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopped")
        mocked_stop.assert_awaited_once_with(sandbox.id)

    def test_stop_provider_sandbox_allows_owner_without_provider_edit(self):
        provider = self._provider_obj()
        sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=self.user.id)
        stopped = self._sandbox_obj(
            provider_id=provider.id,
            owner_id=self.user.id,
            sandbox_id=sandbox.id,
            status="stopped",
            stopped_at=datetime.now(timezone.utc),
        )
        self.db.get = AsyncMock(return_value=types.SimpleNamespace(email="self@example.com"))

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, False)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(side_effect=[sandbox, stopped]),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxManager.stop",
            AsyncMock(return_value=stopped),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["can_stop"])

    def test_stop_provider_sandbox_starting_returns_stopped(self):
        provider = self._provider_obj()
        sandbox = self._sandbox_obj(
            provider_id=provider.id,
            owner_id=self.user.id,
            status="starting",
            started_at=datetime.now(timezone.utc),
        )
        stopped = self._sandbox_obj(
            provider_id=provider.id,
            owner_id=self.user.id,
            sandbox_id=sandbox.id,
            status="stopped",
            stopped_at=datetime.now(timezone.utc),
        )
        self.db.get = AsyncMock(return_value=types.SimpleNamespace(email="self@example.com"))

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, False)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(side_effect=[sandbox, stopped]),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxManager.stop",
            AsyncMock(return_value=stopped),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopped")

    def test_stop_provider_sandbox_forbidden_for_non_owner_without_edit(self):
        provider = self._provider_obj()
        sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=uuid.uuid4())

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, False)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(return_value=sandbox),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 403)

    def test_stop_provider_sandbox_returns_404_for_wrong_provider_binding(self):
        provider = self._provider_obj()
        sandbox_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, True)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox_id}/stop"
            )

        self.assertEqual(response.status_code, 404)

    def test_stop_provider_sandbox_maps_busy_error_to_409(self):
        provider = self._provider_obj()
        sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=self.user.id)

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, True)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(return_value=sandbox),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxManager.stop",
            AsyncMock(side_effect=SandboxBusyError("busy")),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 409)

    def test_stop_provider_sandbox_maps_storage_error_to_500(self):
        provider = self._provider_obj()
        sandbox = self._sandbox_obj(provider_id=provider.id, owner_id=self.user.id)

        with patch(
            "giga_agent.routes.sandboxes.fetch_resource_with_read_and_edit",
            AsyncMock(return_value=(provider, True)),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxRepository.get_by_provider_and_id",
            AsyncMock(return_value=sandbox),
        ), patch(
            "giga_agent.routes.sandboxes.SandboxManager.stop",
            AsyncMock(side_effect=StorageOperationError("failed")),
        ):
            response = self.client.post(
                f"/sandboxes/providers/{provider.id}/sandboxes/{sandbox.id}/stop"
            )

        self.assertEqual(response.status_code, 500)

    def test_get_provider_types_hides_local_for_non_superuser(self):
        self.user.is_superuser = False
        with self._patched_env({"GIGA_AGENT_LOCAL_SANDBOX_ENABLED": "1"}), patch(
            "giga_agent.routes.sandboxes.SandboxRegistry.available_types",
            return_value=["e2b", "local_docker"],
        ):
            response = self.client.get("/sandboxes/providers/types")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["e2b"])

    def test_get_provider_types_shows_local_for_superuser_when_enabled(self):
        with self._patched_env({"GIGA_AGENT_LOCAL_SANDBOX_ENABLED": "1"}), patch(
            "giga_agent.routes.sandboxes.SandboxRegistry.available_types",
            return_value=["e2b", "local_docker"],
        ):
            response = self.client.get("/sandboxes/providers/types")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["e2b", "local_docker"])

    def test_get_local_provider_schema_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        with self._patched_env({"GIGA_AGENT_LOCAL_SANDBOX_ENABLED": "1"}):
            response = self.client.get(
                "/sandboxes/providers/types/local_docker/settings-schema"
            )
        self.assertEqual(response.status_code, 403)

    def test_create_local_provider_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        with self._patched_env({"GIGA_AGENT_LOCAL_SANDBOX_ENABLED": "1"}):
            response = self.client.post(
                "/sandboxes/providers",
                json={
                    "type": "local_docker",
                    "name": "local",
                    "settings": {"max_active_sandboxes": 1},
                    "idle_timeout": 3600,
                    "is_active": True,
                },
            )
        self.assertEqual(response.status_code, 403)
