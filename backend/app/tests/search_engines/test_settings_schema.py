import unittest

from giga_agent.search_engines.registry import SearchEngineRegistry
from giga_agent.search_engines.tavily import TavilySearchEngine


class SearchSettingsSchemaTests(unittest.TestCase):
    def test_tavily_settings_schema_excludes_runtime_fields(self):
        schema = TavilySearchEngine.settings_schema()

        self.assertIn("api_key", schema.model_fields)
        self.assertNotIn("parallel_calls", schema.model_fields)

    def test_registry_returns_tavily_engine(self):
        cls = SearchEngineRegistry.get("tavily")
        self.assertIs(cls, TavilySearchEngine)

    def test_registry_raises_for_unknown_engine(self):
        with self.assertRaises(ValueError):
            SearchEngineRegistry.get("unknown_engine")
