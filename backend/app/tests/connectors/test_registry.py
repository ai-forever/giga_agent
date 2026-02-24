import os
import unittest
from unittest.mock import patch

import giga_agent.connectors  # noqa: F401
from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.connectors.registry import ConnectorRegistry


class ConnectorRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_contains_expected_types(self):
        types = ConnectorRegistry.available_types()
        self.assertIn("openai", types)
        self.assertIn("gigachat", types)
        self.assertIn("tavily", types)

    async def test_openai_validate_and_connection_kwargs(self):
        settings = await ConnectorRegistry.validate_settings(
            "openai",
            {"api_key": "  sk-test  ", "base_url": "https://api.openai.com/v1/ "},
        )
        self.assertEqual(settings["api_key"], "sk-test")
        self.assertEqual(settings["base_url"], "https://api.openai.com/v1")

        kwargs = ConnectorRegistry.get_connection_kwargs("openai", settings)
        self.assertEqual(kwargs, {"api_key": "sk-test", "base_url": "https://api.openai.com/v1"})

    async def test_openai_validate_requires_key_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                await ConnectorRegistry.validate_settings("openai", {})

    async def test_gigachat_dev_requires_base_url(self):
        with self.assertRaises(ValueError):
            await ConnectorRegistry.validate_settings(
                "gigachat",
                {"gigachat_api_type": "dev", "gigachat_username": "u", "gigachat_password": "p"},
            )

    async def test_tavily_env_fallback(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-env"}, clear=True):
            settings = await ConnectorRegistry.validate_settings("tavily", {})
            self.assertEqual(settings, {})
            kwargs = ConnectorRegistry.get_connection_kwargs("tavily", settings)
            self.assertEqual(kwargs, {"api_key": "tvly-env"})

    async def test_get_runtime_returns_connector_instance(self):
        runtime = await ConnectorRegistry.get_runtime(
            "openai",
            {"api_key": "  sk-test  ", "base_url": "https://api.openai.com/v1/ "},
        )
        self.assertIsInstance(runtime, OpenAIConnector)
        self.assertEqual(runtime.api_key, "sk-test")
        self.assertEqual(runtime.base_url, "https://api.openai.com/v1")
