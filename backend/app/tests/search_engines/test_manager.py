import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.search_engines.manager import SearchEngineManager


class SearchEngineManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_when_user_has_no_current_engine(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(search_engine_id=None)

        with self.assertRaises(ValueError):
            await SearchEngineManager.resolve_for_user(owner_id, user)

    async def test_resolve_raises_for_missing_engine(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(search_engine_id=uuid.uuid4())

        with patch(
            "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(ValueError):
                await SearchEngineManager.resolve_for_user(owner_id, user)

    async def test_resolve_raises_for_inactive_engine(self):
        owner_id = uuid.uuid4()
        engine_id = uuid.uuid4()
        user = types.SimpleNamespace(search_engine_id=engine_id)
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=owner_id,
            is_active=False,
            type="tavily",
            settings={},
        )

        with patch(
            "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ):
            with self.assertRaises(ValueError):
                await SearchEngineManager.resolve_for_user(owner_id, user)

    async def test_resolve_passes_settings_to_runtime(self):
        owner_id = uuid.uuid4()
        engine_id = uuid.uuid4()
        user = types.SimpleNamespace(search_engine_id=engine_id)
        record = types.SimpleNamespace(
            id=engine_id,
            owner_id=owner_id,
            is_active=True,
            type="tavily",
            settings={"api_key": "tvly"},
        )
        captured: dict = {}

        class _RuntimeStub:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def init(self):
                captured["initialized"] = True

        with patch(
            "giga_agent.search_engines.manager.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.search_engines.manager.SearchEngineRegistry.get",
            return_value=_RuntimeStub,
        ):
            runtime = await SearchEngineManager.resolve_for_user(owner_id, user)

        self.assertIsInstance(runtime, _RuntimeStub)
        self.assertTrue(captured.get("initialized"))
        self.assertEqual(captured["kwargs"], {"api_key": "tvly"})
