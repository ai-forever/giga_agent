import asyncio
import unittest

from giga_agent.search_engines.registry import SearchEngineRegistry
from giga_agent.search_engines.tavily import TavilySearchEngine


class SearchSettingsSchemaTests(unittest.TestCase):
    def test_tavily_settings_schema_excludes_runtime_and_connector_fields(self):
        schema = TavilySearchEngine.settings_schema()

        self.assertIn("search_depth", schema.model_fields)
        self.assertIn("max_results", schema.model_fields)
        self.assertIn("topic", schema.model_fields)
        self.assertNotIn("parallel_calls", schema.model_fields)
        self.assertNotIn("connector", schema.model_fields)

    def test_tavily_validate_settings_does_not_require_credentials(self):
        validated = asyncio.run(
            TavilySearchEngine.validate_settings({"search_depth": "advanced"})
        )
        self.assertEqual(validated, {"search_depth": "advanced", "max_results": 5})

    def test_registry_returns_tavily_engine(self):
        cls = SearchEngineRegistry.get("tavily")
        self.assertIs(cls, TavilySearchEngine)

    def test_registry_raises_for_unknown_engine(self):
        with self.assertRaises(ValueError):
            SearchEngineRegistry.get("unknown_engine")
