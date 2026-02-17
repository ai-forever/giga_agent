import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user, router


class AuthRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
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
            settings={"theme": "dark", "keep": "value"},
            secrets={"api_key": "old", "keep_secret": "value"},
            llm_id=None,
            fast_llm_id=None,
            embedding_id=None,
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
        ) as mocked_validate_llm, patch(
            "giga_agent.modules.auth.api._validate_fast_llm_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_fast_llm, patch(
            "giga_agent.modules.auth.api._validate_embedding_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_embedding, patch(
            "giga_agent.modules.auth.api._validate_image_generator_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_image, patch(
            "giga_agent.modules.auth.api._validate_search_engine_id",
            AsyncMock(return_value=None),
        ) as mocked_validate_search:
            response = self.client.patch(
                "/users/me",
                json={
                    "llm_id": None,
                    "fast_llm_id": None,
                    "embedding_id": None,
                    "image_generator_id": None,
                    "search_engine_id": None,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["llm_id"])
        self.assertIsNone(payload["fast_llm_id"])
        self.assertIsNone(payload["embedding_id"])
        self.assertIsNone(payload["image_generator_id"])
        self.assertIsNone(payload["search_engine_id"])
        mocked_validate_llm.assert_not_awaited()
        mocked_validate_fast_llm.assert_not_awaited()
        mocked_validate_embedding.assert_not_awaited()
        mocked_validate_image.assert_not_awaited()
        mocked_validate_search.assert_not_awaited()

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
        self.assertEqual(response.json()["detail"], "secrets must be an object when provided")


if __name__ == "__main__":
    unittest.main()
