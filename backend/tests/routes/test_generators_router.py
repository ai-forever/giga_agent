import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.generators.image import router


class GeneratorsRouterTests(unittest.TestCase):
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
        created = self._generator_obj(
            generator_type="openai", connector_id=uuid.uuid4()
        )

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"model": "dall-e-3"}),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=created.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
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

    def test_create_generator_with_permissions_for_superuser(self):
        created = self._generator_obj(
            generator_type="openai", connector_id=uuid.uuid4()
        )

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"model": "dall-e-3"}),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=created.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ResourcePermissionRepository.set_read_acl",
                AsyncMock(return_value=None),
            ) as mocked_set_acl,
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "openai",
                    "settings": {"model": "dall-e-3"},
                    "connector_id": str(created.connector_id),
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

    def test_create_generator_with_permissions_forbidden_for_non_superuser(self):
        self.user.is_superuser = False

        with patch(
            "giga_agent.routes.generators.image._resolve_runtime_cls",
            return_value=types.SimpleNamespace(
                supported_connector_types=lambda: ["openai"]
            ),
        ) as mocked_resolve_runtime:
            response = self.client.post(
                "/image",
                json={
                    "type": "openai",
                    "settings": {"model": "dall-e-3"},
                    "connector_id": str(uuid.uuid4()),
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

    def test_get_image_generators_includes_can_edit(self):
        owned = self._generator_obj()
        writable = self._generator_obj(owner_id=uuid.uuid4())
        readonly = self._generator_obj(owner_id=uuid.uuid4())

        with patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.list_readable_with_edit_for_user",
            AsyncMock(
                return_value=[(owned, True), (writable, True), (readonly, False)]
            ),
        ):
            response = self.client.get("/image")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        can_edit_by_id = {item["id"]: item["can_edit"] for item in payload}
        self.assertTrue(can_edit_by_id[str(owned.id)])
        self.assertTrue(can_edit_by_id[str(writable.id)])
        self.assertFalse(can_edit_by_id[str(readonly.id)])

    def test_get_generator_types_meta(self):
        runtime_map = {
            "openai": types.SimpleNamespace(
                supported_connector_types=lambda: ["openai"]
            ),
            "fusion_brain": types.SimpleNamespace(supported_connector_types=lambda: []),
        }

        with (
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRegistry.available_types",
                return_value=["openai", "fusion_brain"],
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRegistry.get",
                side_effect=lambda generator_type: runtime_map[generator_type],
            ),
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

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: []
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"api_key": "k", "secret_key": "s"}),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
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

    def test_create_grok_imagine_without_connector(self):
        created = self._generator_obj(
            generator_type="grok_imagine",
            connector_id=None,
            settings={"api_key": "xai-key", "model": "grok-imagine"},
        )

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: []
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"api_key": "xai-key", "model": "grok-imagine"}),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "grok_imagine",
                    "settings": {"api_key": "xai-key", "model": "grok-imagine"},
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "grok_imagine")
        self.assertIsNone(response.json()["connector_id"])

    def test_create_nano_banana_without_connector(self):
        created = self._generator_obj(
            generator_type="nano_banana",
            connector_id=None,
            settings={"api_key": "google-key", "model": "gemini-2.5-flash-image"},
        )

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: []
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(
                    return_value={
                        "api_key": "google-key",
                        "model": "gemini-2.5-flash-image",
                    }
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "nano_banana",
                    "settings": {
                        "api_key": "google-key",
                        "model": "gemini-2.5-flash-image",
                    },
                    "is_active": True,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "nano_banana")
        self.assertIsNone(response.json()["connector_id"])

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

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"model": "gpt-image-1"}),
            ) as mocked_validate_settings,
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=existing.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(return_value=updated),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"settings": {"model": "gpt-image-1"}, "name": "updated"},
            )

        self.assertEqual(response.status_code, 200)
        mocked_validate_settings.assert_awaited_once_with(
            "openai", {"model": "gpt-image-1"}
        )

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

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: []
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"api_key": "k2", "secret_key": "s2"}),
            ) as mocked_validate_settings,
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(return_value=updated),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
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

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=existing.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(return_value=updated),
            ),
            patch(
                "giga_agent.routes.generators.image.clear_user_current_link_if_matches",
                AsyncMock(return_value=True),
            ) as mocked_clear_current,
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"is_active": False},
            )

        self.assertEqual(response.status_code, 200)
        mocked_clear_current.assert_awaited_once()

    def test_create_skips_connection_check_when_disabled(self):
        created = self._generator_obj(
            generator_type="openai", connector_id=uuid.uuid4()
        )

        with (
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_settings",
                AsyncMock(return_value={"model": "dall-e-3"}),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=created.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ) as mocked_check,
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.create",
                AsyncMock(return_value=created),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(created),
            ),
        ):
            response = self.client.post(
                "/image",
                json={
                    "type": "openai",
                    "settings": {"model": "dall-e-3"},
                    "connector_id": str(created.connector_id),
                    "is_active": True,
                    "check_connection": False,
                },
            )

        self.assertEqual(response.status_code, 201)
        mocked_check.assert_not_awaited()

    def test_patch_returns_422_when_connection_check_fails(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            connector_id=uuid.uuid4(),
            is_active=True,
        )

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=existing.connector_id),
            ),
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(side_effect=HTTPException(status_code=422, detail="boom")),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(),
            ) as mocked_update,
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"name": "updated"},
            )

        self.assertEqual(response.status_code, 422)
        mocked_update.assert_not_awaited()

    def test_patch_allows_clearing_name_and_connector(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            generator_type="openai",
            connector_id=uuid.uuid4(),
        )
        updated = self._generator_obj(
            generator_id=generator_id,
            generator_type="openai",
            connector_id=None,
        )
        updated.name = None

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ) as mocked_validate_connector,
            patch(
                "giga_agent.routes.generators.image._check_connection_or_http_error",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(return_value=updated),
            ) as mocked_update,
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.to_response",
                return_value=self._response_payload(updated),
            ),
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"name": None, "connector_id": None},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["name"])
        self.assertIsNone(response.json()["connector_id"])
        self.assertIsNone(mocked_validate_connector.await_args.kwargs["connector_id"])
        self.assertIsNone(mocked_update.await_args.kwargs["name"])
        self.assertIsNone(mocked_update.await_args.kwargs["connector_id"])

    def test_patch_rejects_null_is_active(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(
            generator_id=generator_id,
            generator_type="openai",
            connector_id=None,
        )

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image._resolve_runtime_cls",
                return_value=types.SimpleNamespace(
                    supported_connector_types=lambda: ["openai"]
                ),
            ),
            patch(
                "giga_agent.routes.generators.image._validate_connector_link",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.update",
                AsyncMock(),
            ) as mocked_update,
        ):
            response = self.client.patch(
                f"/image/{generator_id}",
                json={"is_active": None},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "is_active must not be null when provided",
        )
        mocked_update.assert_not_awaited()

    def test_delete_current_auto_clears_current(self):
        generator_id = uuid.uuid4()
        existing = self._generator_obj(generator_id=generator_id)

        with (
            patch(
                "giga_agent.routes.generators.image._get_generator_with_write_check",
                AsyncMock(return_value=existing),
            ),
            patch(
                "giga_agent.routes.generators.image.ImageGeneratorRepository.delete",
                AsyncMock(return_value=None),
            ),
            patch(
                "giga_agent.routes.generators.image.clear_user_current_link_if_matches",
                AsyncMock(return_value=True),
            ) as mocked_clear_current,
        ):
            response = self.client.delete(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 204)
        mocked_clear_current.assert_awaited_once()

    def test_owner_check_returns_403(self):
        generator_id = uuid.uuid4()
        generator = self._generator_obj(generator_id=generator_id)

        with patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.get_by_id_with_access_for_user",
            AsyncMock(return_value=(generator, False, False)),
        ):
            response = self.client.get(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 403)

    def test_not_found_returns_404(self):
        generator_id = uuid.uuid4()

        with patch(
            "giga_agent.routes.generators.image.ImageGeneratorRepository.get_by_id_with_access_for_user",
            AsyncMock(return_value=None),
        ):
            response = self.client.get(f"/image/{generator_id}")

        self.assertEqual(response.status_code, 404)


class BaseImageGeneratorCheckConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_connection_calls_generate_image_with_ping_probe(self):
        class _Runtime(BaseImageGenerator):
            async def init(self) -> None:
                await super().init()

            async def _generate_image(
                self,
                prompt: str,
                width: int | None = None,
                height: int | None = None,
                **kwargs,
            ) -> str:
                return "ok"

        runtime = _Runtime()
        runtime._generate_image = AsyncMock(return_value="ok")

        result = await runtime.check_connection()

        self.assertTrue(result)
        runtime._generate_image.assert_awaited_once_with("ping", 256, 256)

    async def test_generate_image_passes_kwargs_and_none_dimensions_to_provider(self):
        class _Runtime(BaseImageGenerator):
            async def init(self) -> None:
                await super().init()

            async def _generate_image(
                self,
                prompt: str,
                width: int | None = None,
                height: int | None = None,
                **kwargs,
            ) -> str:
                return "ok"

        runtime = _Runtime()
        await runtime.init()
        runtime._generate_image = AsyncMock(return_value="ok")

        result = await runtime.generate_image("prompt", None, None, foo="bar")

        self.assertEqual(result, "ok")
        runtime._generate_image.assert_awaited_once_with(
            "prompt",
            None,
            None,
            foo="bar",
        )
