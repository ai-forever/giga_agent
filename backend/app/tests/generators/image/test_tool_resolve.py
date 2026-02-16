import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.fusion_brain import FusionBrainImageGen
from giga_agent.generators.image.openai import OpenAIImageGen
from giga_agent.generators.image.tool import (
    _resolve_generator_for_user,
    _resolve_llm_for_image_generator,
)


class ImageToolResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_llm_for_image_generator_type_mismatch(self):
        owner_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        record = types.SimpleNamespace(
            llm_provider_id=provider_id,
            type="openai",
        )
        provider = types.SimpleNamespace(
            id=provider_id,
            owner_id=owner_id,
            is_active=True,
            type="gigachat",
            settings={},
        )

        with patch(
            "giga_agent.generators.image.tool.LLMProviderRepository.get_by_id",
            AsyncMock(return_value=provider),
        ):
            with self.assertRaises(ValueError):
                await _resolve_llm_for_image_generator(
                    owner_id=owner_id,
                    record=record,
                    session=object(),
                    runtime_cls=OpenAIImageGen,
                )

    async def test_resolve_llm_for_image_generator_disallowed_for_runtime(self):
        owner_id = uuid.uuid4()
        record = types.SimpleNamespace(
            llm_provider_id=uuid.uuid4(),
            type="fusion_brain",
        )

        with self.assertRaises(ValueError):
            await _resolve_llm_for_image_generator(
                owner_id=owner_id,
                record=record,
                session=object(),
                runtime_cls=FusionBrainImageGen,
            )

    async def test_resolve_generator_passes_llm_and_settings_fields(self):
        owner_id = uuid.uuid4()
        gen_id = uuid.uuid4()
        fake_llm = object()

        user = types.SimpleNamespace(image_generator_id=gen_id)
        record = types.SimpleNamespace(
            id=gen_id,
            owner_id=owner_id,
            is_active=True,
            type="openai",
            settings={"model": "gpt-image-1", "timeout": 30.0},
            llm_provider_id=uuid.uuid4(),
        )

        captured: dict = {}

        class _RuntimeStub:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def init(self):
                captured["initialized"] = True

        @asynccontextmanager
        async def _factory_ctx():
            yield object()

        fake_factory = lambda: _factory_ctx()

        with patch(
            "giga_agent.generators.image.tool.get_session_factory",
            AsyncMock(return_value=fake_factory),
        ), patch(
            "giga_agent.generators.image.tool.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.generators.image.tool._resolve_llm_for_image_generator",
            AsyncMock(return_value=fake_llm),
        ), patch(
            "giga_agent.generators.image.tool.ImageGeneratorRegistry.get",
            return_value=_RuntimeStub,
        ):
            generator = await _resolve_generator_for_user(owner_id, user)

        self.assertIsInstance(generator, _RuntimeStub)
        self.assertTrue(captured.get("initialized"))
        self.assertEqual(captured["kwargs"]["model"], "gpt-image-1")
        self.assertEqual(captured["kwargs"]["timeout"], 30.0)
        self.assertIs(captured["kwargs"]["llm"], fake_llm)
        self.assertNotIn("settings", captured["kwargs"])

    async def test_resolve_generator_raises_for_missing_generator(self):
        owner_id = uuid.uuid4()
        gen_id = uuid.uuid4()
        user = types.SimpleNamespace(image_generator_id=gen_id)

        @asynccontextmanager
        async def _factory_ctx():
            yield object()

        fake_factory = lambda: _factory_ctx()

        with patch(
            "giga_agent.generators.image.tool.get_session_factory",
            AsyncMock(return_value=fake_factory),
        ), patch(
            "giga_agent.generators.image.tool.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "не найден"):
                await _resolve_generator_for_user(owner_id, user)

    async def test_resolve_generator_raises_for_inactive_generator(self):
        owner_id = uuid.uuid4()
        gen_id = uuid.uuid4()
        user = types.SimpleNamespace(image_generator_id=gen_id)
        record = types.SimpleNamespace(
            id=gen_id,
            owner_id=owner_id,
            is_active=False,
            type="openai",
            settings={"model": "gpt-image-1"},
            llm_provider_id=uuid.uuid4(),
        )

        @asynccontextmanager
        async def _factory_ctx():
            yield object()

        fake_factory = lambda: _factory_ctx()

        with patch(
            "giga_agent.generators.image.tool.get_session_factory",
            AsyncMock(return_value=fake_factory),
        ), patch(
            "giga_agent.generators.image.tool.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ):
            with self.assertRaisesRegex(ValueError, "неактивен"):
                await _resolve_generator_for_user(owner_id, user)
