import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from langchain.tools import tool

from giga_agent.modules.search import SearchModule


@tool
def provider_search_tool(queries: list[str]) -> list[str]:
    """Provider-specific search tool stub."""
    return queries


class _RuntimeStub:
    @classmethod
    def get_tools(cls):
        return [provider_search_tool]


class SearchModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_disabled_without_current_engine(self):
        module = SearchModule()
        user = types.SimpleNamespace(search_engine_id=None)

        tools = await module.get_tools(user=user, agent=object())
        instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_enabled_with_current_engine(self):
        module = SearchModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), search_engine_id=uuid.uuid4())
        record = types.SimpleNamespace(
            id=user.search_engine_id,
            owner_id=user.id,
            type="tavily",
            is_active=True,
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.search.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.search.module.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.modules.search.module.SearchEngineRegistry.get",
            return_value=_RuntimeStub,
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "provider_search_tool")
        self.assertIsNotNone(instructions)
        self.assertIn("search", instructions)

    async def test_module_returns_no_tools_for_invalid_engine_ref(self):
        module = SearchModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), search_engine_id=uuid.uuid4())

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.search.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.search.module.SearchEngineRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)
