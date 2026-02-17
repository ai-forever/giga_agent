import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.llm.manager import LLMManager


class LLMManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_llm(self):
        llm_id = uuid.uuid4()

        with patch(
            "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                await LLMManager.resolve_by_id(llm_id)

    async def test_resolve_raises_for_inactive_llm(self):
        llm_id = uuid.uuid4()
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
                await LLMManager.resolve_by_id(llm_id)

    async def test_resolve_builds_chat_model(self):
        llm_id = uuid.uuid4()
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

        built_model = object()

        class _RuntimeStub:
            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return connector_type == "openai"

            @classmethod
            def build_chat_model_from_kwargs(
                cls,
                *,
                model_id: str,
                connection_kwargs: dict,
                llm_settings: dict | None = None,
            ):
                if model_id != "gpt-4o-mini":
                    raise AssertionError("unexpected model_id")
                if connection_kwargs != {"api_key": "sk-test"}:
                    raise AssertionError("unexpected kwargs")
                if llm_settings != {"temperature": 0.2}:
                    raise AssertionError("unexpected settings")
                return built_model

        with patch(
            "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=llm),
        ), patch(
            "giga_agent.llm.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.llm.manager.LLMRegistry.get",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.llm.manager.ConnectorRegistry.get_connection_kwargs",
            return_value={"api_key": "sk-test"},
        ):
            resolved = await LLMManager.resolve_by_id(llm_id)

        self.assertIs(resolved, built_model)

    async def test_resolve_raises_when_connector_is_incompatible(self):
        llm_id = uuid.uuid4()
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

        with patch(
            "giga_agent.llm.manager.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=llm),
        ), patch(
            "giga_agent.llm.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.llm.manager.LLMRegistry.get",
            return_value=_RuntimeStub,
        ):
            with self.assertRaisesRegex(ValueError, "not compatible"):
                await LLMManager.resolve_by_id(llm_id)
