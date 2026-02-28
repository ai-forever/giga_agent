import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.generators.image import router


class GeneratorsRouterTests(unittest.TestCase):
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

    def _generator_obj(
        self,
        *,
        generator_id: uuid.UUID | None = None,
        generator_type: str = "openai",
        owner_id: uuid.UUID | None = None,
        settings: dict | None = None,
        connector_id: uuid.UUID | None = None,
        is_active: bool = True,
    ):
        return types.SimpleNamespace(
            id=generator_id or uuid.uuid4(),
            owner_id=owner_id or self.user.id,
            type=generator_type,
            name="gen",
            settings=settings or {"model": "dall-e-3"},
            connector_id=connector_id,
            is_active=is_active,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def _response_payload(self, generator_obj) -> dict:
        return {
            "id": str(generator_obj.id),
            "owner_id": str(generator_obj.owner_id),
            "type": generator_obj.type,
            "name": generator_obj.name,
            "settings": generator_obj.settings,
            "connector_id": (
                str(generator_obj.connector_id)
                if generator_obj.connector_id is not None
                else None
            ),
            "is_active": generator_obj.is_active,
            "created_at": generator_obj.created_at,
            "updated_at": generator_obj.updated_at,
        }

    def test_create_success_for_supported_type_with_connector(self):
        created = self._generator_obj(generator_type="openai", connector_id=uuid.uuid4())

        with patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["openai"]),
        ), patch(
            "giga_agent.routes.generators.image._validate_settings",
            AsyncMock(return_value={"model": "dall-e-3"}),
        ), patch(
            "giga_agent.routes.generators.image._validate_connector_link",
            AsyncMock(return_value=created.connector_id),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
            return_value=self._response_payload(created),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "openai",
                    "name": "OpenAI Gen",
                    "settings": {"model": "dall-e-3"},
                    "connector_id": str(created.connector_id),
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "openai")

    def test_get_generator_types_meta(self):
        runtime_map = {
            "openai": types.SimpleNamespace(
                supported_connector_types=lambda: ["openai"]
            ),
            "fusion_brain": types.SimpleNamespace(
                supported_connector_types=lambda: []
            ),
        }

        with patch(
            "giga_agent.routes.generators.image.ImageGeneratorRegistry.available_types",
            return_value=["openai", "fusion_brain"],
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRegistry.get",
            side_effect=lambda generator_type: runtime_map[generator_type],
        ):
            response = self.client.get("/image/types/meta")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload,
            [
                {
                    "type": "openai",
                    "supported_connector_types": ["openai"],
                    "requires_connector": True,
                },
                {
                    "type": "fusion_brain",
                    "supported_connector_types": [],
                    "requires_connector": False,
                },
            ],
        )

    def test_create_success_for_unsupported_type_without_connector(self):
        created = self._generator_obj(generator_type="fusion_brain", connector_id=None)

        with patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: []),
        ), patch(
            "giga_agent.routes.generators.image._validate_settings",
            AsyncMock(return_value={"api_key": "k", "secret_key": "s"}),
        ), patch(
            "giga_agent.routes.generators.image._validate_connector_link",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
            AsyncMock(return_value=created),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
            return_value=self._response_payload(created),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "fusion_brain",
                    "settings": {"api_key": "k", "secret_key": "s"},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "fusion_brain")

    def test_patch_with_type_returns_422(self):
        response = self.client.patch(
            f"/image/{uuid.uuid4()}",
            json={"type": "gigachat"},
        )

        self.assertEqual(response.status_code, 422)

    def test_patch_without_type_updates_allowed_fields(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            generator_type="openai",
            connector_id=uuid.uuid4(),
            settings={"model": "dall-e-3"},
        )
        updated = self._generator_obj(
            generator_id=generator_id,
            generator_type="openai",
            connector_id=existing.connector_id,
            settings={"model": "gpt-image-1"},
        )

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["openai"]),
        ), patch(
            "giga_agent.routes.generators.image._validate_settings",
            AsyncMock(return_value={"model": "gpt-image-1"}),
        ) as mocked_validate_settings, patch(
            "giga_agent.routes.generators.image._validate_connector_link",
            AsyncMock(return_value=existing.connector_id),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
            return_value=self._response_payload(updated),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"settings": {"model": "gpt-image-1"}, "name": "updated"},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_settings.assert_awaited_once_with("openai", {"model": "gpt-image-1"})

    def test_patch_settings_uses_current_generator_type(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            generator_type="fusion_brain",
            connector_id=None,
            settings={"api_key": "k", "secret_key": "s"},
        )
        updated = self._generator_obj(
            generator_id=generator_id,
            generator_type="fusion_brain",
            connector_id=None,
            settings={"api_key": "k2", "secret_key": "s2"},
        )

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: []),
        ), patch(
            "giga_agent.routes.generators.image._validate_settings",
            AsyncMock(return_value={"api_key": "k2", "secret_key": "s2"}),
        ) as mocked_validate_settings, patch(
            "giga_agent.routes.generators.image._validate_connector_link",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
            return_value=self._response_payload(updated),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"settings": {"api_key": "k2", "secret_key": "s2"}},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_settings.assert_awaited_once_with(
            "fusion_brain", {"api_key": "k2", "secret_key": "s2"}
        )

    def test_deactivate_current_auto_clears_current(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            connector_id=uuid.uuid4(),
            is_active=True,
        )
        updated = self._generator_obj(
            generator_id=generator_id,
            connector_id=existing.connector_id,
            is_active=False,
        )

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(supported_connector_types=lambda: ["openai"]),
        ), patch(
            "giga_agent.routes.generators.image._validate_connector_link",
            AsyncMock(return_value=existing.connector_id),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
            AsyncMock(return_value=updated),
        ), patch(
            "giga_agent.routes.generators.image._clear_current_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current, patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
            return_value=self._response_payload(updated),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"is_active": False},
            )

        self.assertEqual(response.status_code, 200)
        mocked_clear_current.assert_awaited_once()

    def test_delete_current_auto_clears_current(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(generator_id=generator_id)

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_owner_check",
            AsyncMock(return_value=existing),
        ), patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.delete",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.generators.image._clear_current_if_matches",
            AsyncMock(return_value=True),
        ) as mocked_clear_current:
            response = self.client.delete(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 204)
        mocked_clear_current.assert_awaited_once()

    def test_owner_check_returns_403(self):
        generator_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_read_check",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=403,
                    detail="Access denied",
                )
            ),
        ):
            response = self.client.get(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 403)

    def test_not_found_returns_404(self):
        generator_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.generators.image._get_generator_with_read_check",
            AsyncMock(
                side_effect=HTTPException(
                    status_code=404,
                    detail="Image generator not found",
                )
            ),
        ):
            response = self.client.get(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 404)
