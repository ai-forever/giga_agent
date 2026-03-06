import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.resource_permissions import router


class ResourcePermissionsRouterTests(unittest.TestCase):
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

    def test_get_permissions_success_for_superuser(self):
        resource_id = uuid.uuid4()
        payload = {
            "read_user_ids": [str(uuid.uuid4())],
            "read_group_ids": [str(uuid.uuid4())],
            "public_read": True,
        }
        with patch(
            "giga_agent.routes.resource_permissions._ensure_resource_exists",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.resource_permissions.ResourcePermissionRepository.get_read_acl",
            AsyncMock(return_value=payload),
        ) as mocked_get:
            response = self.client.get(
                f"/resource-permissions/connector/{resource_id}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked_get.assert_awaited_once()

    def test_get_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        response = self.client.get(
            f"/resource-permissions/connector/{uuid.uuid4()}",
        )
        self.assertEqual(response.status_code, 403)

    def test_put_permissions_success_for_superuser(self):
        resource_id = uuid.uuid4()
        payload = {
            "read_user_ids": [str(uuid.uuid4())],
            "read_group_ids": [str(uuid.uuid4())],
            "public_read": False,
        }
        with patch(
            "giga_agent.routes.resource_permissions._ensure_resource_exists",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.resource_permissions.ResourcePermissionRepository.set_read_acl",
            AsyncMock(return_value=None),
        ) as mocked_set, patch(
            "giga_agent.routes.resource_permissions.ResourcePermissionRepository.get_read_acl",
            AsyncMock(return_value=payload),
        ) as mocked_get:
            response = self.client.put(
                f"/resource-permissions/llm/{resource_id}",
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked_set.assert_awaited_once()
        mocked_get.assert_awaited_once()

    def test_put_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False
        response = self.client.put(
            f"/resource-permissions/embedding/{uuid.uuid4()}",
            json={
                "read_user_ids": [],
                "read_group_ids": [],
                "public_read": False,
            },
        )
        self.assertEqual(response.status_code, 403)
