import types
import unittest
import uuid
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
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_search_engine=True,
            get_search_engine=AsyncMock(return_value=_RuntimeStub()),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)
            instructions = await module.get_instructions(
                user=user, agent=object(), config=config
            )

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "provider_search_tool")
        self.assertIsNotNone(instructions)
        self.assertIn("search", instructions)

    async def test_module_returns_no_tools_for_invalid_engine_ref(self):
        module = SearchModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), search_engine_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_search_engine=False,
            get_search_engine=AsyncMock(),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)
            instructions = await module.get_instructions(
                user=user, agent=object(), config=config
            )

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)
