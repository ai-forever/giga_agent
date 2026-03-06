import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import giga_agent.connectors  # noqa: F401
from giga_agent.connectors.gigachat import GigaChatConnector
from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.connectors.tavily import TavilyConnector


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

    async def test_openai_check_connection_uses_models_list(self):
        connector = OpenAIConnector(api_key="sk-test", base_url="https://api.openai.com/v1")
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=[])
        with patch(
            "giga_agent.connectors.openai.AsyncOpenAI",
            return_value=mock_client,
        ) as mocked_client:
            result = await connector.check_connection()

        self.assertTrue(result)
        mocked_client.assert_called_once()
        mock_client.models.list.assert_awaited_once()

    async def test_gigachat_check_connection_uses_aget_models(self):
        connector = GigaChatConnector(gigachat_api_type="prod")
        mock_llm = AsyncMock()
        mock_llm.aget_models = AsyncMock(return_value=[])
        with patch(
            "giga_agent.connectors.gigachat.GigaChat",
            return_value=mock_llm,
        ) as mocked_llm:
            result = await connector.check_connection()

        self.assertTrue(result)
        mocked_llm.assert_called_once()
        mock_llm.aget_models.assert_awaited_once()

    async def test_tavily_check_connection_uses_usage_endpoint(self):
        connector = TavilyConnector(api_key="tvly-test")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock(return_value=None)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        with patch(
            "giga_agent.connectors.tavily.httpx.AsyncClient",
            return_value=mock_client,
        ) as mocked_client:
            result = await connector.check_connection()

        self.assertTrue(result)
        mocked_client.assert_called_once_with(timeout=30.0)
        mock_client.get.assert_awaited_once_with(
            "https://api.tavily.com/usage",
            headers={"Authorization": "Bearer tvly-test"},
        )
        mock_response.raise_for_status.assert_called_once()

    async def test_tavily_check_connection_maps_401_to_value_error(self):
        connector = TavilyConnector(api_key="tvly-test")
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status = Mock(return_value=None)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        with patch(
            "giga_agent.connectors.tavily.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with self.assertRaises(ValueError) as ctx:
                await connector.check_connection()

        self.assertIn("unauthorized (401)", str(ctx.exception))
