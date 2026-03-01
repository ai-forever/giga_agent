import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user, router
from giga_agent.modules.auth.events import UserEmbeddingChangedEvent


class _ModuleStub:
    def __init__(self, secrets):
        self._secrets = secrets

    def get_secrets(self):
        return self._secrets


class AuthRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            is_superuser=True,
            email="admin@example.com",
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

    def _user_model(self):
        return types.SimpleNamespace(
            id=self.user.id,
            email="user@example.com",
            first_name=None,
            last_name=None,
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            settings={"theme": "dark", "keep": "value"},
            secrets={"api_key": "old", "keep_secret": "value"},
            llm_id=None,
            fast_llm_id=None,
            embedding_id=None,
            sandbox_provider_id=None,
            image_generator_id=None,
            search_engine_id=None,
        )

    def test_patch_users_me_updates_only_provided_fields_and_merges_settings(self):
        user_model = self._user_model()
        new_llm_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_llm, patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_invalidate_cache:
            response = self.client.patch(
                "/users/me",
                json={
                    "settings": {"theme": "light"},
                    "secrets": {"api_key": "new"},
                    "llm_id": str(new_llm_id),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["settings"]["theme"], "light")
        self.assertEqual(payload["settings"]["keep"], "value")
        self.assertEqual(payload["secrets"]["api_key"], "new")
        self.assertEqual(payload["secrets"]["keep_secret"], "value")
        self.assertEqual(payload["llm_id"], str(new_llm_id))
        self.assertIsNone(payload["fast_llm_id"])
        mocked_validate_llm.assert_awaited_once_with(self.db, self.user.id, new_llm_id)
        mocked_invalidate_cache.assert_awaited_once_with(self.user.id)

    def test_patch_users_me_allows_null_to_reset_ids(self):
        user_model = self._user_model()
        user_model.llm_id = uuid.uuid4()
        user_model.fast_llm_id = uuid.uuid4()
        user_model.embedding_id = uuid.uuid4()
        user_model.sandbox_provider_id = uuid.uuid4()
        user_model.image_generator_id = uuid.uuid4()
        user_model.search_engine_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_fast_llm, patch(
            "giga_agent.modules.auth.api._validate_embedding_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_embedding, patch(
            "giga_agent.modules.auth.api._validate_sandbox_provider_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_sandbox_provider, patch(
            "giga_agent.modules.auth.api._validate_image_generator_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_image, patch(
            "giga_agent.modules.auth.api._validate_search_engine_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_search, patch(
            "giga_agent.modules.auth.api.cache.delete_match",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                "/users/me",
                json={
                    "llm_id": None,
                    "fast_llm_id": None,
                    "embedding_id": None,
                    "sandbox_provider_id": None,
                    "image_generator_id": None,
                    "search_engine_id": None,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["llm_id"])
        self.assertIsNone(payload["fast_llm_id"])
        self.assertIsNone(payload["embedding_id"])
        self.assertIsNone(payload["sandbox_provider_id"])
        self.assertIsNone(payload["image_generator_id"])
        self.assertIsNone(payload["search_engine_id"])
        mocked_validate_fast_llm.assert_not_awaited()
        mocked_validate_embedding.assert_not_awaited()
        mocked_validate_sandbox_provider.assert_not_awaited()
        mocked_validate_image.assert_not_awaited()
        mocked_validate_search.assert_not_awaited()

    def test_patch_users_me_updates_sandbox_provider_id(self):
        user_model = self._user_model()
        sandbox_provider_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_sandbox_provider_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_sandbox_provider, patch(
            "giga_agent.modules.auth.api.cache.delete_match",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                "/users/me",
                json={"sandbox_provider_id": str(sandbox_provider_id)},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sandbox_provider_id"], str(sandbox_provider_id))
        mocked_validate_sandbox_provider.assert_awaited_once_with(
            self.db,
            self.user.id,
            sandbox_provider_id,
        )

    def test_patch_users_me_publishes_embedding_changed_event(self):
        user_model = self._user_model()
        old_embedding_id = uuid.uuid4()
        new_embedding_id = uuid.uuid4()
        user_model.embedding_id = old_embedding_id

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_embedding_id",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
            response = self.client.patch(
                "/users/me",
                json={"embedding_id": str(new_embedding_id)},
            )

        self.assertEqual(response.status_code, 200)
        mocked_publish.assert_awaited_once()
        event = mocked_publish.await_args.args[0]
        self.assertIsInstance(event, UserEmbeddingChangedEvent)
        self.assertEqual(event.user_id, self.user.id)
        self.assertEqual(event.old_embedding_id, old_embedding_id)
        self.assertEqual(event.new_embedding_id, new_embedding_id)

    def test_patch_users_me_does_not_publish_embedding_event_without_change(self):
        user_model = self._user_model()
        user_model.embedding_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
            response = self.client.patch(
                "/users/me",
                json={"settings": {"theme": "light"}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_publish.assert_not_awaited()

    def test_patch_users_me_returns_422_for_invalid_sandbox_provider_reference(self):
        user_model = self._user_model()
        invalid_provider_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_sandbox_provider_id",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=422,
                    detail="Invalid value for sandbox_provider_id",
                )
            ),
        ):
            response = self.client.patch(
                "/users/me",
                json={"sandbox_provider_id": str(invalid_provider_id)},
            )

        self.assertEqual(response.status_code, 422)

    def test_patch_users_me_returns_422_for_invalid_reference(self):
        user_model = self._user_model()
        invalid_llm_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=422,
                    detail="Invalid value for llm_id",
                )
            ),
        ):
            response = self.client.patch(
                "/users/me",
                json={"llm_id": str(invalid_llm_id)},
            )

        self.assertEqual(response.status_code, 422)

    def test_patch_users_me_returns_422_when_secrets_is_null(self):
        user_model = self._user_model()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ):
            response = self.client.patch(
                "/users/me",
                json={"secrets": None},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"], "secrets must be an object when provided"
        )

    def test_patch_users_me_validates_llm_id_secret_when_present(self):
        user_model = self._user_model()
        llm_secret_id = uuid.uuid4()
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_llm, patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                "/users/me",
                json={"secrets": {"ASSISTANT_LLM": str(llm_secret_id)}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_llm.assert_awaited_once_with(
            self.db, self.user.id, llm_secret_id, field_name="secrets.ASSISTANT_LLM"
        )

    def test_patch_users_me_returns_422_for_invalid_uuid_in_llm_id_secret(self):
        user_model = self._user_model()
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ):
            response = self.client.patch(
                "/users/me",
                json={"secrets": {"ASSISTANT_LLM": "not-a-uuid"}},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("secrets.ASSISTANT_LLM", response.json()["detail"])

    def test_patch_users_me_returns_422_for_inaccessible_llm_id_secret(self):
        user_model = self._user_model()
        llm_secret_id = uuid.uuid4()
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=422, detail="Invalid value for llm_id"
                )
            ),
        ):
            response = self.client.patch(
                "/users/me",
                json={"secrets": {"ASSISTANT_LLM": str(llm_secret_id)}},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Invalid value for llm_id", response.json()["detail"])

    def test_patch_users_me_skips_llm_secret_validation_for_empty_value(self):
        user_model = self._user_model()
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=user_model),
        ), patch(
            "giga_agent.modules.auth.api._validate_llm_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_llm, patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                "/users/me",
                json={"secrets": {"ASSISTANT_LLM": "   "}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_llm.assert_not_awaited()

    def test_get_users_returns_list_for_superuser(self):
        users = [
            types.SimpleNamespace(
                id=uuid.uuid4(),
                email="one@example.com",
                first_name="One",
                last_name="User",
                hashed_password="x",
                is_active=True,
                is_superuser=False,
                created_at="2026-02-27T00:00:00Z",
                updated_at="2026-02-27T00:00:00Z",
                settings=None,
                secrets=None,
                llm_id=None,
                fast_llm_id=None,
                embedding_id=None,
                sandbox_provider_id=None,
                image_generator_id=None,
                search_engine_id=None,
            )
        ]

        with patch(
            "giga_agent.modules.auth.api.UserRepository.get_all",
            AsyncMock(return_value=users),
        ):
            response = self.client.get("/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["email"], "one@example.com")

    def test_get_users_forbidden_for_non_superuser(self):
        non_super = types.SimpleNamespace(
            **{**self.user.__dict__, "is_superuser": False}
        )

        async def _override_current_user():
            return non_super

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 403)

    def test_create_user_forbidden_for_non_superuser(self):
        non_super = types.SimpleNamespace(
            **{**self.user.__dict__, "is_superuser": False}
        )

        async def _override_current_user():
            return non_super

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        response = self.client.post(
            "/users",
            json={
                "email": "new@example.com",
                "password": "secret123",
                "is_active": True,
                "is_superuser": False,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_create_user_returns_400_for_duplicate_email(self):
        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=True),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "dup@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Email already registered")

    def test_create_user_with_group_ids_assigns_memberships(self):
        group_id_1 = uuid.uuid4()
        group_id_2 = uuid.uuid4()
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "new@example.com"

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ) as mocked_create, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[group_id_1, group_id_2]),
        ) as mocked_existing_groups, patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ) as mocked_add_users, patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ) as mocked_publish:
            response = self.client.post(
                "/users",
                json={
                    "email": "new@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "group_ids": [str(group_id_1), str(group_id_2)],
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_existing_groups.assert_awaited_once_with([group_id_1, group_id_2])
        mocked_create.assert_awaited_once()
        self.assertEqual(mocked_add_users.await_count, 2)
        mocked_add_users.assert_any_await(group_id_1, [created_user.id], commit=False)
        mocked_add_users.assert_any_await(group_id_2, [created_user.id], commit=False)
        self.db.commit.assert_awaited_once()
        self.db.refresh.assert_awaited_once_with(created_user)
        mocked_publish.assert_awaited_once()

    def test_create_user_without_group_ids_skips_group_assignment(self):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "new-no-groups@example.com"

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ) as mocked_create, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ) as mocked_existing_groups, patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ) as mocked_add_users, patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "new-no-groups@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_create.assert_awaited_once()
        mocked_existing_groups.assert_not_awaited()
        mocked_add_users.assert_not_awaited()
        self.db.commit.assert_awaited_once()

    def test_create_user_returns_422_when_some_group_ids_missing(self):
        existing_group_id = uuid.uuid4()
        missing_group_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[existing_group_id]),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(),
        ) as mocked_create:
            response = self.client.post(
                "/users",
                json={
                    "email": "missing-group@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "group_ids": [str(existing_group_id), str(missing_group_id)],
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn(str(missing_group_id), response.json()["detail"])
        mocked_create.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    def test_create_user_deduplicates_group_ids_before_assignment(self):
        group_id = uuid.uuid4()
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "new-dedup@example.com"

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[group_id]),
        ) as mocked_existing_groups, patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ) as mocked_add_users, patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "new-dedup@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "group_ids": [str(group_id), str(group_id)],
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_existing_groups.assert_awaited_once_with([group_id])
        mocked_add_users.assert_awaited_once_with(
            group_id, [created_user.id], commit=False
        )

    def test_create_user_copies_runtime_ids_grants_read_permissions_and_copies_module_secrets(
        self,
    ):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-copy@example.com"
        created_user.secrets = None

        shared_llm_id = uuid.uuid4()
        owner_model = self._user_model()
        owner_model.llm_id = shared_llm_id
        owner_model.fast_llm_id = shared_llm_id
        owner_model.embedding_id = uuid.uuid4()
        owner_model.image_generator_id = uuid.uuid4()
        owner_model.search_engine_id = uuid.uuid4()
        owner_model.sandbox_provider_id = uuid.uuid4()
        owner_model.secrets = {"MODULE_KEY": "secret-value"}

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=owner_model),
        ) as mocked_owner_model, patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(
                return_value=types.SimpleNamespace(created=[], existing=[], errors=[])
            ),
        ) as mocked_grant_permissions, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ) as mocked_add_users, patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-copy@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": True,
                    "copy_owner_module_secrets": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(created_user.llm_id, owner_model.llm_id)
        self.assertEqual(created_user.fast_llm_id, owner_model.fast_llm_id)
        self.assertEqual(created_user.embedding_id, owner_model.embedding_id)
        self.assertEqual(
            created_user.image_generator_id, owner_model.image_generator_id
        )
        self.assertEqual(created_user.search_engine_id, owner_model.search_engine_id)
        self.assertEqual(
            created_user.sandbox_provider_id, owner_model.sandbox_provider_id
        )
        self.assertEqual(created_user.secrets, {"MODULE_KEY": "secret-value"})
        mocked_owner_model.assert_awaited_once_with(self.db, self.user.id)
        mocked_add_users.assert_not_awaited()
        self.db.commit.assert_awaited_once()

        mocked_grant_permissions.assert_awaited_once()
        grant_kwargs = mocked_grant_permissions.await_args.kwargs
        self.assertEqual(grant_kwargs["no_commit"], True)
        items = grant_kwargs["items"]
        self.assertEqual(len(items), 5)
        seen = {
            (item.resource_type, item.resource_id, item.owner_id, item.permission)
            for item in items
        }
        self.assertEqual(
            seen,
            {
                ("llm", owner_model.llm_id, created_user.id, "read"),
                ("embedding", owner_model.embedding_id, created_user.id, "read"),
                (
                    "image_generator",
                    owner_model.image_generator_id,
                    created_user.id,
                    "read",
                ),
                (
                    "search_engine",
                    owner_model.search_engine_id,
                    created_user.id,
                    "read",
                ),
                ("sandbox", owner_model.sandbox_provider_id, created_user.id, "read"),
            },
        )

    def test_create_user_ignores_module_secrets_toggle_when_runtime_copy_is_disabled(
        self,
    ):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-disabled@example.com"
        created_user.secrets = None

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(),
        ) as mocked_owner_model, patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(),
        ) as mocked_grant_permissions, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-disabled@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": False,
                    "copy_owner_module_secrets": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_owner_model.assert_not_awaited()
        mocked_grant_permissions.assert_not_awaited()
        self.assertIsNone(created_user.secrets)

    def test_create_user_does_not_copy_module_secrets_when_flag_is_disabled(self):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-no-module-secrets@example.com"
        created_user.secrets = None

        owner_model = self._user_model()
        owner_model.llm_id = uuid.uuid4()
        owner_model.secrets = {"MODULE_KEY": "secret-value"}

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=owner_model),
        ), patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(
                return_value=types.SimpleNamespace(created=[], existing=[], errors=[])
            ),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-no-module-secrets@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": True,
                    "copy_owner_module_secrets": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(created_user.secrets)

    def test_create_user_grants_acl_for_runtime_ids_found_in_module_secret_metadata(
        self,
    ):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-secrets-acl@example.com"
        created_user.secrets = None

        field_llm_id = uuid.uuid4()
        secret_llm_id = uuid.uuid4()

        owner_model = self._user_model()
        owner_model.llm_id = field_llm_id
        owner_model.fast_llm_id = None
        owner_model.embedding_id = None
        owner_model.image_generator_id = None
        owner_model.search_engine_id = None
        owner_model.sandbox_provider_id = None
        owner_model.secrets = {
            "ASSISTANT_LLM": str(secret_llm_id),
            "PASS_SECRET": str(uuid.uuid4()),
            "TEXT_SECRET": str(uuid.uuid4()),
            "UNKNOWN_LLM": str(uuid.uuid4()),
        }
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                        {"name": "PASS_SECRET", "description": "pass", "type": "pass"},
                        {"name": "TEXT_SECRET", "description": "text", "type": "text"},
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=owner_model),
        ), patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(
                return_value=types.SimpleNamespace(created=[], existing=[], errors=[])
            ),
        ) as mocked_grant_permissions, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-secrets-acl@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": True,
                    "copy_owner_module_secrets": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(created_user.secrets, owner_model.secrets)
        mocked_grant_permissions.assert_awaited_once()
        items = mocked_grant_permissions.await_args.kwargs["items"]
        seen = {(item.resource_type, item.resource_id) for item in items}
        self.assertEqual(
            seen,
            {
                ("llm", field_llm_id),
                ("llm", secret_llm_id),
            },
        )

    def test_create_user_includes_known_module_secret_llm_ids_and_skips_invalid_uuid(
        self,
    ):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-secrets-invalid@example.com"
        created_user.secrets = None

        field_llm_id = uuid.uuid4()
        foreign_llm_id = uuid.uuid4()
        owner_model = self._user_model()
        owner_model.llm_id = field_llm_id
        owner_model.secrets = {
            "ASSISTANT_LLM": "not-a-uuid",
            "FOREIGN_LLM": str(foreign_llm_id),
        }
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                        {"name": "FOREIGN_LLM", "description": "LLM", "type": "llm_id"},
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=owner_model),
        ), patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(
                return_value=types.SimpleNamespace(created=[], existing=[], errors=[])
            ),
        ) as mocked_grant_permissions, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-secrets-invalid@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": True,
                    "copy_owner_module_secrets": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_grant_permissions.assert_awaited_once()
        items = mocked_grant_permissions.await_args.kwargs["items"]
        self.assertEqual(
            {(item.resource_type, item.resource_id) for item in items},
            {("llm", field_llm_id), ("llm", foreign_llm_id)},
        )

    def test_create_user_deduplicates_llm_acl_between_runtime_field_and_module_secret(
        self,
    ):
        created_user = self._user_model()
        created_user.id = uuid.uuid4()
        created_user.email = "runtime-secrets-dedup@example.com"

        shared_llm_id = uuid.uuid4()
        owner_model = self._user_model()
        owner_model.llm_id = shared_llm_id
        owner_model.fast_llm_id = None
        owner_model.secrets = {"ASSISTANT_LLM": str(shared_llm_id)}
        self.app.state.agent = types.SimpleNamespace(
            all_modules=[
                _ModuleStub(
                    [
                        {
                            "name": "ASSISTANT_LLM",
                            "description": "LLM",
                            "type": "llm_id",
                        },
                    ]
                )
            ]
        )

        with patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="hashed",
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.create",
            AsyncMock(return_value=created_user),
        ), patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=owner_model),
        ), patch(
            "giga_agent.modules.auth.api.ResourcePermissionRepository.grant_permissions",
            AsyncMock(
                return_value=types.SimpleNamespace(created=[], existing=[], errors=[])
            ),
        ) as mocked_grant_permissions, patch(
            "giga_agent.modules.auth.api.GroupRepository.get_existing_group_ids",
            AsyncMock(return_value=[]),
        ), patch(
            "giga_agent.modules.auth.api.GroupRepository.add_users",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.modules.auth.api.event_bus.publish",
            AsyncMock(return_value=None),
        ):
            response = self.client.post(
                "/users",
                json={
                    "email": "runtime-secrets-dedup@example.com",
                    "password": "secret123",
                    "is_active": True,
                    "is_superuser": False,
                    "copy_owner_runtime_ids": True,
                    "copy_owner_module_secrets": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        items = mocked_grant_permissions.await_args.kwargs["items"]
        self.assertEqual(
            [(item.resource_type, item.resource_id) for item in items],
            [("llm", shared_llm_id)],
        )

    def test_patch_user_by_id_updates_fields_for_superuser(self):
        target = self._user_model()
        target.id = uuid.uuid4()
        target.email = "old@example.com"

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=False),
        ) as mocked_exists_by_email, patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ) as mocked_invalidate_cache:
            response = self.client.patch(
                f"/users/{target.id}",
                json={
                    "email": "updated@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "is_active": False,
                    "is_superuser": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["email"], "updated@example.com")
        self.assertEqual(payload["first_name"], "John")
        self.assertEqual(payload["last_name"], "Doe")
        self.assertFalse(payload["is_active"])
        self.assertTrue(payload["is_superuser"])
        mocked_exists_by_email.assert_awaited_once_with("updated@example.com")
        mocked_invalidate_cache.assert_awaited_once_with(target.id)

    def test_patch_user_by_id_updates_password(self):
        target = self._user_model()
        target.id = uuid.uuid4()
        target.hashed_password = "old-hash"

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ), patch(
            "giga_agent.modules.auth.api.security.get_password_hash",
            return_value="new-hash",
        ) as mocked_hash, patch(
            "giga_agent.modules.auth.api.UserRepository.invalidate_cache",
            AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                f"/users/{target.id}",
                json={"password": "new-password"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target.hashed_password, "new-hash")
        mocked_hash.assert_called_once_with("new-password")

    def test_patch_user_by_id_returns_422_for_empty_password(self):
        target = self._user_model()
        target.id = uuid.uuid4()

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ):
            response = self.client.patch(
                f"/users/{target.id}",
                json={"password": "   "},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "password must not be empty")

    def test_patch_user_by_id_returns_400_for_duplicate_email(self):
        target = self._user_model()
        target.id = uuid.uuid4()
        target.email = "old@example.com"

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.exists_by_email",
            AsyncMock(return_value=True),
        ):
            response = self.client.patch(
                f"/users/{target.id}",
                json={"email": "dup@example.com"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Email already registered")

    def test_patch_user_by_id_returns_422_for_self_flags_update(self):
        target = self._user_model()
        target.id = self.user.id

        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ):
            response = self.client.patch(
                f"/users/{target.id}",
                json={"is_superuser": False},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "Cannot change is_active or is_superuser for current user",
        )

    def test_patch_user_by_id_forbidden_for_non_superuser(self):
        non_super = types.SimpleNamespace(
            **{**self.user.__dict__, "is_superuser": False}
        )

        async def _override_current_user():
            return non_super

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        response = self.client.patch(
            f"/users/{uuid.uuid4()}",
            json={"first_name": "Updated"},
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_user_by_id_returns_404_for_missing_user(self):
        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(
                side_effect=HTTPException(status_code=404, detail="User not found")
            ),
        ):
            response = self.client.patch(
                f"/users/{uuid.uuid4()}",
                json={"first_name": "Updated"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "User not found")

    def test_delete_user_returns_204_for_superuser(self):
        target = types.SimpleNamespace(
            id=uuid.uuid4(),
            email="target@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
        )
        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(return_value=target),
        ), patch(
            "giga_agent.modules.auth.api.UserRepository.delete",
            AsyncMock(return_value=None),
        ) as mocked_delete:
            response = self.client.delete(f"/users/{target.id}")

        self.assertEqual(response.status_code, 204)
        mocked_delete.assert_awaited_once_with(target)

    def test_delete_user_returns_422_for_self_delete(self):
        response = self.client.delete(f"/users/{self.user.id}")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Cannot delete current user")

    def test_delete_user_returns_404_for_missing_user(self):
        with patch(
            "giga_agent.modules.auth.api._get_user_model_by_id",
            AsyncMock(
                side_effect=HTTPException(status_code=404, detail="User not found")
            ),
        ):
            response = self.client.delete(f"/users/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "User not found")

    def test_delete_user_forbidden_for_non_superuser(self):
        non_super = types.SimpleNamespace(
            **{**self.user.__dict__, "is_superuser": False}
        )

        async def _override_current_user():
            return non_super

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        response = self.client.delete(f"/users/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
