import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.conf import GIGA_PREFIX_API
from giga_agent.models.users import ROLE_ADMIN, ROLE_MEMBER
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes import router as api_router
from giga_agent.routes.groups import router


class GroupsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.superuser = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            is_superuser=True,
            role=ROLE_ADMIN,
            email="admin@example.com",
            settings=None,
            secrets=None,
            llm_id=None,
            fast_llm_id=None,
            embedding_id=None,
            sandbox_provider_id=None,
            image_generator_id=None,
            search_engine_id=None,
        )
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.superuser

        async def _override_get_session():
            yield object()

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    def _group_obj(
        self,
        *,
        group_id: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
        name: str = "team",
    ):
        return types.SimpleNamespace(
            id=group_id or uuid.uuid4(),
            owner_id=owner_id or self.superuser.id,
            name=name,
            description="desc",
            data={"a": 1},
            permissions={"role": "reader"},
            created_at="2026-02-27T00:00:00Z",
            updated_at="2026-02-27T00:00:00Z",
        )

    def _group_payload(self, group_obj) -> dict:
        return {
            "id": str(group_obj.id),
            "owner_id": str(group_obj.owner_id),
            "name": group_obj.name,
            "description": group_obj.description,
            "data": group_obj.data,
            "permissions": group_obj.permissions,
            "users_count": 0,
            "created_at": group_obj.created_at,
            "updated_at": group_obj.updated_at,
        }

    def _user_short_payload(self, user_id: uuid.UUID, email: str) -> dict:
        return {
            "id": str(user_id),
            "email": email,
            "first_name": None,
            "last_name": None,
            "is_active": True,
            "is_superuser": False,
            "role": ROLE_MEMBER,
            "settings": None,
            "secrets": None,
            "image_generator_id": None,
            "search_engine_id": None,
            "embedding_id": None,
            "llm_id": None,
            "fast_llm_id": None,
            "sandbox_provider_id": None,
            "is_synthetic": False,
            "experimental_mode": True,
        }

    def test_superuser_guard_forbidden(self):
        non_super = types.SimpleNamespace(
            **{**self.superuser.__dict__, "is_superuser": False}
        )

        async def _override_non_super():
            return non_super

        self.app.dependency_overrides[get_current_active_user] = _override_non_super
        response = self.client.get("/groups")
        self.assertEqual(response.status_code, 403)

    def test_create_group_without_owner_uses_current_user(self):
        created = self._group_obj(owner_id=self.superuser.id)
        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.create",
                AsyncMock(return_value=created),
            ) as mocked_create,
            patch(
                "giga_agent.routes.groups.GroupRepository.to_response",
                return_value=self._group_payload(created),
            ),
            patch(
                "giga_agent.routes.groups._ensure_user_exists",
                AsyncMock(return_value=None),
            ),
        ):
            response = self.client.post(
                "/groups",
                json={"name": "team", "description": "desc"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["owner_id"], str(self.superuser.id))
        self.assertEqual(mocked_create.await_args.kwargs["owner_id"], self.superuser.id)

    def test_create_group_with_owner_id(self):
        owner_id = uuid.uuid4()
        created = self._group_obj(owner_id=owner_id)

        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.create",
                AsyncMock(return_value=created),
            ) as mocked_create,
            patch(
                "giga_agent.routes.groups.GroupRepository.to_response",
                return_value=self._group_payload(created),
            ),
            patch(
                "giga_agent.routes.groups._ensure_user_exists",
                AsyncMock(return_value=None),
            ),
        ):
            response = self.client.post(
                "/groups",
                json={"owner_id": str(owner_id), "name": "team"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(mocked_create.await_args.kwargs["owner_id"], owner_id)

    def test_get_group_ids_by_user(self):
        user_id = uuid.uuid4()
        group_ids = [uuid.uuid4(), uuid.uuid4()]
        with patch(
            "giga_agent.routes.groups.GroupRepository.get_group_ids_by_user_id",
            AsyncMock(return_value=group_ids),
        ):
            response = self.client.get(f"/groups/by-user/{user_id}/ids")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], str(user_id))
        self.assertEqual(
            response.json()["group_ids"], [str(group_id) for group_id in group_ids]
        )

    def test_add_group_users_atomic_strict_error(self):
        group = self._group_obj()
        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.get_by_id",
                AsyncMock(return_value=group),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.add_users",
                AsyncMock(side_effect=ValueError("Users not found: x")),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.get_group_users",
                AsyncMock(return_value=[]),
            ),
        ):
            response = self.client.post(
                f"/groups/{group.id}/users",
                json={"user_ids": [str(uuid.uuid4())]},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Users not found", response.json()["detail"])

    def test_remove_group_user_not_found(self):
        group = self._group_obj()
        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.get_by_id",
                AsyncMock(return_value=group),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.remove_user",
                AsyncMock(return_value=False),
            ),
        ):
            response = self.client.delete(f"/groups/{group.id}/users/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_get_group_users_returns_user_short(self):
        group = self._group_obj()
        member_id = uuid.uuid4()
        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.get_by_id",
                AsyncMock(return_value=group),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.get_group_users",
                AsyncMock(
                    return_value=[
                        types.SimpleNamespace(
                            id=member_id,
                            email="member@example.com",
                            first_name=None,
                            last_name=None,
                            is_active=True,
                            is_superuser=False,
                            role=ROLE_MEMBER,
                            settings=None,
                            secrets=None,
                            image_generator_id=None,
                            search_engine_id=None,
                            embedding_id=None,
                            llm_id=None,
                            fast_llm_id=None,
                            sandbox_provider_id=None,
                        )
                    ]
                ),
            ),
        ):
            response = self.client.get(f"/groups/{group.id}/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0],
            self._user_short_payload(member_id, "member@example.com"),
        )

    def test_groups_router_connected_to_api_prefix(self):
        app = FastAPI()
        app.include_router(api_router)

        async def _override_current_user():
            return self.superuser

        async def _override_get_session():
            yield object()

        app.dependency_overrides[get_current_active_user] = _override_current_user
        app.dependency_overrides[get_session] = _override_get_session

        client = TestClient(app)
        with patch(
            "giga_agent.routes.groups.GroupRepository.list_all",
            AsyncMock(return_value=[]),
        ):
            response = client.get(f"{GIGA_PREFIX_API}/groups")
        self.assertEqual(response.status_code, 200)

    def test_patch_group_allows_clearing_nullable_fields(self):
        group = self._group_obj()
        updated = self._group_obj(group_id=group.id)
        updated.description = None
        updated.data = None
        updated.permissions = None

        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.get_by_id",
                AsyncMock(return_value=group),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.update",
                AsyncMock(return_value=updated),
            ) as mocked_update,
            patch(
                "giga_agent.routes.groups.GroupRepository.get_user_counts",
                AsyncMock(return_value={group.id: 0}),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.to_response",
                return_value=self._group_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/groups/{group.id}",
                json={"description": None, "data": None, "permissions": None},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["description"])
        self.assertIsNone(mocked_update.await_args.kwargs["description"])
        self.assertIsNone(mocked_update.await_args.kwargs["data"])
        self.assertIsNone(mocked_update.await_args.kwargs["permissions"])

    def test_patch_group_rejects_null_name(self):
        group = self._group_obj()

        with (
            patch(
                "giga_agent.routes.groups.GroupRepository.get_by_id",
                AsyncMock(return_value=group),
            ),
            patch(
                "giga_agent.routes.groups.GroupRepository.update",
                AsyncMock(),
            ) as mocked_update,
        ):
            response = self.client.patch(
                f"/groups/{group.id}",
                json={"name": None},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "name must not be null when provided",
        )
        mocked_update.assert_not_awaited()

    def test_patch_group_rejects_unknown_fields(self):
        response = self.client.patch(
            f"/groups/{uuid.uuid4()}",
            json={"unknown_field": True},
        )

        self.assertEqual(response.status_code, 422)
