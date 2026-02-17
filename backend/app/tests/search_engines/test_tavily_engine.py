import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.search_engines.tavily import TavilySearchEngine


class TavilySearchEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_init_uses_api_key_from_settings(self):
        fake_tool = object()

        with patch(
            "giga_agent.search_engines.tavily.TavilySearch",
            return_value=fake_tool,
        ) as mocked_tavily:
            engine = TavilySearchEngine(api_key="tvly-settings")
            await engine.init()

        mocked_tavily.assert_called_once_with(tavily_api_key="tvly-settings")
        self.assertIs(engine._search_tool, fake_tool)

    async def test_search_returns_query_result_pairs(self):
        fake_tool = AsyncMock()
        fake_tool.abatch = AsyncMock(return_value=[{"url": "https://a"}, {"url": "https://b"}])

        engine = TavilySearchEngine(api_key="tvly-settings")
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

    async def test_validate_settings_allows_env_fallback(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-env"}, clear=False):
            validated = await TavilySearchEngine.validate_settings({})
        self.assertEqual(validated, {})

    async def test_validate_settings_requires_api_key_without_env(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                await TavilySearchEngine.validate_settings({})
