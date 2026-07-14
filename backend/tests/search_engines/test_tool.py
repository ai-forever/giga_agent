import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.search_engines.tool import search


class SearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_tool_requires_runtime(self):
        assert search.coroutine is not None
        with self.assertRaises(ValueError):
            await search.coroutine(queries=["q1"], runtime=None)

    async def test_search_tool_raises_when_resolver_missing(self):
        # No RuntimeResolver injected into config -> from_config raises ValueError.
        runtime = types.SimpleNamespace(config={"configurable": {}})

        assert search.coroutine is not None
        with self.assertRaises(ValueError):
            await search.coroutine(queries=["q1"], runtime=runtime)

    async def test_search_tool_raises_when_engine_not_selected(self):
        runtime = types.SimpleNamespace(config={"configurable": {}})
        resolver = types.SimpleNamespace(
            has_search_engine=False,
            get_search_engine=AsyncMock(),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            assert search.coroutine is not None
            with self.assertRaises(ValueError):
                await search.coroutine(queries=["q1"], runtime=runtime)

        resolver.get_search_engine.assert_not_awaited()

    async def test_search_tool_returns_engine_result(self):
        runtime = types.SimpleNamespace(config={"configurable": {}})
        engine = types.SimpleNamespace(
            search=AsyncMock(return_value=[{"query": "q1", "result": {"ok": True}}])
        )
        resolver = types.SimpleNamespace(
            has_search_engine=True,
            get_search_engine=AsyncMock(return_value=engine),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            assert search.coroutine is not None
            result = await search.coroutine(queries=["q1"], runtime=runtime)

        resolver.get_search_engine.assert_awaited_once_with()
        engine.search.assert_awaited_once_with(["q1"])
        self.assertEqual(result, [{"query": "q1", "result": {"ok": True}}])
