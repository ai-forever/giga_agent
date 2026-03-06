import types
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401
from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.connectors.gigachat import GigaChatConnector
from giga_agent.llm.gigachat import GigaChatRuntime
from giga_agent.llm.openai import OpenAIRuntime
from giga_agent.llm.registry import LLMRegistry


class LLMRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_contains_expected_types(self):
        types = LLMRegistry.available_types()
        self.assertIn("openai", types)
        self.assertIn("gigachat", types)

    def test_supported_connector_types(self):
        self.assertEqual(OpenAIRuntime.supported_connector_types(), ["openai"])
        self.assertEqual(GigaChatRuntime.supported_connector_types(), ["gigachat"])

    async def test_openai_fetch_available_models(self):
        mock_client = types.SimpleNamespace(
            models=types.SimpleNamespace(
                list=AsyncMock(
                    return_value=types.SimpleNamespace(
                        data=[
                            types.SimpleNamespace(
                                id="gpt-4o", created=1, owned_by="openai"
                            ),
                            types.SimpleNamespace(
                                id="gpt-4o-mini", created=2, owned_by="openai"
                            ),
                        ]
                    )
                )
            )
        )
        with patch("giga_agent.llm.openai.AsyncOpenAI", return_value=mock_client):
            connector = OpenAIConnector(api_key="sk-test")
            models = await OpenAIRuntime.fetch_available_models(
                connector=connector,
            )

        self.assertEqual([item.id for item in models], ["gpt-4o", "gpt-4o-mini"])

    async def test_gigachat_fetch_available_models(self):
        mock_llm = types.SimpleNamespace(
            aget_models=AsyncMock(
                return_value=types.SimpleNamespace(
                    data=[types.SimpleNamespace(id_="GigaChat", owned_by="sber")]
                )
            )
        )

        with patch(
            "giga_agent.llm.gigachat.get_gigachat_access_token_cached",
            AsyncMock(return_value="tok"),
        ), patch("giga_agent.llm.gigachat.GigaChat", return_value=mock_llm):
            connector = GigaChatConnector(
                gigachat_api_type="prod",
                gigachat_credentials="token",
            )
            models = await GigaChatRuntime.fetch_available_models(
                connector=connector,
            )

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "GigaChat")
