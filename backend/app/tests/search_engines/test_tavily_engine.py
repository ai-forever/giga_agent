import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.connectors.tavily import TavilyConnector
from giga_agent.search_engines.tavily import TavilySearchEngine


class TavilySearchEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_init_uses_api_key_from_connector_api_object(self):
        fake_tool = object()
        connector = TavilyConnector(api_key="tvly-connector")

        with patch(
            "giga_agent.search_engines.tavily.TavilySearch",
            return_value=fake_tool,
        ) as mocked_tavily:
            engine = TavilySearchEngine(connector=connector)
            await engine.init()

        mocked_tavily.assert_called_once_with(
            tavily_api_key="tvly-connector",
            search_depth="basic",
            max_results=5,
            topic=None,
        )
        self.assertIs(engine._search_tool, fake_tool)

    async def test_search_returns_query_result_pairs(self):
        fake_tool = AsyncMock()
        fake_tool.abatch = AsyncMock(return_value=[{"url": "https://a"}, {"url": "https://b"}])

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-env"}, clear=True):
            engine = TavilySearchEngine()
            with patch(
                "giga_agent.search_engines.tavily.TavilySearch",
                return_value=fake_tool,
            ):
                await engine.init()

        result = await engine.search(["query 1", " query 2 "])

        fake_tool.abatch.assert_awaited_once_with(
            [{"query": "query 1"}, {"query": "query 2"}]
        )
        self.assertEqual(
            result,
            [
                {"query": "query 1", "result": {"url": "https://a"}},
                {"query": "query 2", "result": {"url": "https://b"}},
            ],
        )

    async def test_init_uses_env_when_connector_is_missing(self):
        fake_tool = object()

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-env"}, clear=True), patch(
            "giga_agent.search_engines.tavily.TavilySearch",
            return_value=fake_tool,
        ) as mocked_tavily:
            engine = TavilySearchEngine()
            await engine.init()

        mocked_tavily.assert_called_once_with(
            tavily_api_key="tvly-env",
            search_depth="basic",
            max_results=5,
            topic=None,
        )

    async def test_init_requires_api_key_when_connector_and_env_are_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                await TavilySearchEngine().init()
