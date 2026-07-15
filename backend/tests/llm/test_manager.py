import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.llm.manager import LLMManager


class LLMManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_llm(self):
        llm_id = uuid.uuid4()
        session = object()

        with patch(
            "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                await LLMManager.resolve_by_id(llm_id, session=session)

    async def test_resolve_raises_for_inactive_llm(self):
        llm_id = uuid.uuid4()
        session = object()
        llm = types.SimpleNamespace(
            id=llm_id,
            is_active=False,
            connector_id=uuid.uuid4(),
            type="openai",
            model_id="gpt-4o-mini",
            settings={},
        )

        with patch(
            "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=llm),
        ):
            with self.assertRaisesRegex(ValueError, "inactive"):
                await LLMManager.resolve_by_id(llm_id, session=session)

    async def test_resolve_returns_runtime(self):
        llm_id = uuid.uuid4()
        session = object()
        connector_id = uuid.uuid4()
        llm = types.SimpleNamespace(
            id=llm_id,
            is_active=True,
            connector_id=connector_id,
            type="openai",
            model_id="gpt-4o-mini",
            settings={"temperature": 0.2},
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="openai",
            settings={"api_key": "sk-test"},
        )
        connector_runtime = types.SimpleNamespace()

        class _RuntimeStub:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return connector_type == "openai"

            @classmethod
            async def validate_settings(cls, settings: dict) -> dict:
                return settings

        with (
            patch(
                "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
                AsyncMock(return_value=llm),
            ),
            patch(
                "giga_agent.llm.manager.ConnectorRepository.get_cached_or_db",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.llm.manager.LLMRegistry.get",
                return_value=_RuntimeStub,
            ),
            patch(
                "giga_agent.llm.manager.ConnectorRegistry.get_runtime",
                AsyncMock(return_value=connector_runtime),
            ),
        ):
            resolved = await LLMManager.resolve_by_id(llm_id, session=session)

        self.assertIsInstance(resolved, _RuntimeStub)
        self.assertEqual(resolved.kwargs["connector"], connector_runtime)
        self.assertEqual(resolved.kwargs["model_id"], "gpt-4o-mini")
        self.assertEqual(resolved.kwargs["temperature"], 0.2)

    async def test_resolve_raises_when_connector_is_incompatible(self):
        llm_id = uuid.uuid4()
        session = object()
        connector_id = uuid.uuid4()
        llm = types.SimpleNamespace(
            id=llm_id,
            is_active=True,
            connector_id=connector_id,
            type="openai",
            model_id="gpt-4o-mini",
            settings={},
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="gigachat",
            settings={},
        )

        class _RuntimeStub:
            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return False

        with (
            patch(
                "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
                AsyncMock(return_value=llm),
            ),
            patch(
                "giga_agent.llm.manager.ConnectorRepository.get_cached_or_db",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.llm.manager.LLMRegistry.get",
                return_value=_RuntimeStub,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "not compatible"):
                await LLMManager.resolve_by_id(llm_id, session=session)
