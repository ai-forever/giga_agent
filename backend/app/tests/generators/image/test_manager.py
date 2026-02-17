import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.manager import ImageGeneratorManager


class ImageGeneratorManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_generator(self):
        gen_id = uuid.uuid4()

        with patch(
            "giga_agent.generators.image.manager.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "не найден"):
                await ImageGeneratorManager.resolve_by_id(gen_id)

    async def test_resolve_raises_for_inactive_generator(self):
        gen_id = uuid.uuid4()
        record = types.SimpleNamespace(
            id=gen_id,
            is_active=False,
            type="openai",
            settings={},
            connector_id=uuid.uuid4(),
        )

        with patch(
            "giga_agent.generators.image.manager.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ):
            with self.assertRaisesRegex(ValueError, "неактивен"):
                await ImageGeneratorManager.resolve_by_id(gen_id)

    async def test_resolve_builds_generator_using_connector_api_object(self):
        gen_id = uuid.uuid4()
        connector_id = uuid.uuid4()
        record = types.SimpleNamespace(
            id=gen_id,
            is_active=True,
            type="openai",
            settings={"model": "gpt-image-1", "timeout": 30.0},
            connector_id=connector_id,
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="openai",
            settings={"api_key": "sk-test"},
        )
        fake_llm = object()

        captured: dict = {}

        class _RuntimeStub:
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def init(self):
                captured["initialized"] = True

        with patch(
            "giga_agent.generators.image.manager.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.generators.image.manager.ImageGeneratorRegistry.get",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.generators.image.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.generators.image.manager.ConnectorRegistry.get_api_object",
            return_value=fake_llm,
        ) as mocked_api_object:
            generator = await ImageGeneratorManager.resolve_by_id(gen_id)

        mocked_api_object.assert_called_once_with("openai", {"api_key": "sk-test"})
        self.assertIsInstance(generator, _RuntimeStub)
        self.assertTrue(captured.get("initialized"))
        self.assertEqual(captured["kwargs"]["model"], "gpt-image-1")
        self.assertEqual(captured["kwargs"]["timeout"], 30.0)
        self.assertIs(captured["kwargs"]["llm"], fake_llm)

    async def test_resolve_raises_for_unsupported_connector_type(self):
        gen_id = uuid.uuid4()
        connector_id = uuid.uuid4()
        record = types.SimpleNamespace(
            id=gen_id,
            is_active=True,
            type="openai",
            settings={},
            connector_id=connector_id,
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="gigachat",
            settings={},
        )

        class _RuntimeStub:
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

        with patch(
            "giga_agent.generators.image.manager.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.generators.image.manager.ImageGeneratorRegistry.get",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.generators.image.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ):
            with self.assertRaisesRegex(ValueError, "not supported"):
                await ImageGeneratorManager.resolve_by_id(gen_id)
