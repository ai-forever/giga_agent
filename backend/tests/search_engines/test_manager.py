import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.search_engines.manager import SearchEngineManager


class SearchEngineManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_engine(self):
        engine_id = uuid.uuid4()
        session = object()

        with patch(
            "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(ValueError):
                await SearchEngineManager.resolve_by_id(engine_id, session=session)

    async def test_resolve_raises_for_inactive_engine(self):
        engine_id = uuid.uuid4()
        session = object()
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=uuid.uuid4(),
            is_active=False,
            type="tavily",
            settings={},
            connector_id=None,
        )

        with patch(
            "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ):
            with self.assertRaises(ValueError):
                await SearchEngineManager.resolve_by_id(engine_id, session=session)

    async def test_resolve_allows_missing_connector_and_passes_none(self):
        engine_id = uuid.uuid4()
        session = object()
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=uuid.uuid4(),
            is_active=True,
            type="tavily",
            settings={"search_depth": "basic"},
            connector_id=None,
        )

        class _RuntimeStub:
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["tavily"]

            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def init(self):
                return None

        with (
            patch(
                "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
                AsyncMock(return_value=record),
            ),
            patch(
                "giga_agent.search_engines.manager.SearchEngineRegistry.get",
                return_value=_RuntimeStub,
            ),
        ):
            runtime = await SearchEngineManager.resolve_by_id(
                engine_id, session=session
            )

        self.assertIsNone(runtime.kwargs["connector"])
        self.assertEqual(runtime.kwargs["search_depth"], "basic")

    async def test_resolve_passes_settings_and_connector_runtime_to_engine(self):
        engine_id = uuid.uuid4()
        session = object()
        connector_id = uuid.uuid4()
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=uuid.uuid4(),
            is_active=True,
            type="tavily",
            settings={"search_depth": "advanced"},
            connector_id=connector_id,
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            owner_id=uuid.uuid4(),
            is_active=True,
            type="tavily",
            settings={"api_key": "tvly-secret"},
        )

        captured: dict = {}

        class _RuntimeStub:
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["tavily"]

            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def init(self):
                captured["initialized"] = True

        with (
            patch(
                "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
                AsyncMock(return_value=record),
            ),
            patch(
                "giga_agent.search_engines.manager.SearchEngineRegistry.get",
                return_value=_RuntimeStub,
            ),
            patch(
                "giga_agent.search_engines.manager.ConnectorRepository.get_cached_or_db",
                AsyncMock(return_value=connector),
            ),
            patch(
                "giga_agent.search_engines.manager.ConnectorRegistry.get_runtime",
                AsyncMock(return_value="connector-runtime"),
            ),
        ):
            runtime = await SearchEngineManager.resolve_by_id(
                engine_id,
                session=session,
            )

        self.assertIsInstance(runtime, _RuntimeStub)
        self.assertTrue(captured.get("initialized"))
        self.assertEqual(
            captured["kwargs"],
            {"search_depth": "advanced", "connector": "connector-runtime"},
        )

    async def test_resolve_raises_for_unsupported_connector_type(self):
        engine_id = uuid.uuid4()
        session = object()
        connector_id = uuid.uuid4()
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=uuid.uuid4(),
            is_active=True,
            type="tavily",
            settings={"search_depth": "advanced"},
            connector_id=connector_id,
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            owner_id=uuid.uuid4(),
            is_active=True,
            type="openai",
            settings={"api_key": "sk-test"},
        )

        class _RuntimeStub:
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["tavily"]

        with (
            patch(
                "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
                AsyncMock(return_value=record),
            ),
            patch(
                "giga_agent.search_engines.manager.SearchEngineRegistry.get",
                return_value=_RuntimeStub,
            ),
            patch(
                "giga_agent.search_engines.manager.ConnectorRepository.get_cached_or_db",
                AsyncMock(return_value=connector),
            ),
        ):
            with self.assertRaises(ValueError):
                await SearchEngineManager.resolve_by_id(engine_id, session=session)

    def test_resolve_for_user_removed(self):
        self.assertFalse(hasattr(SearchEngineManager, "resolve_for_user"))
