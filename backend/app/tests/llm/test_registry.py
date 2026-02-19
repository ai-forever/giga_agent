import types
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401
from giga_agent.llm.gigachat import GigaChatLLM
from giga_agent.llm.openai import OpenAILLM
from giga_agent.llm.registry import LLMRegistry


class LLMRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_contains_expected_types(self):
        types = LLMRegistry.available_types()
        self.assertIn("openai", types)
        self.assertIn("gigachat", types)

    def test_supported_connector_types(self):
        self.assertEqual(OpenAILLM.supported_connector_types(), ["openai"])
        self.assertEqual(GigaChatLLM.supported_connector_types(), ["gigachat"])

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
            models = await OpenAILLM.fetch_available_models(
                connector_type="openai",
                connector_settings={"api_key": "sk-test"},
            )

        self.assertEqual([item.id for item in models], ["gpt-4o", "gpt-4o-mini"])

    def test_openai_build_chat_model_from_kwargs(self):
        with patch("giga_agent.llm.openai.ChatOpenAI", return_value=object()) as mocked:
            OpenAILLM.build_chat_model_from_kwargs(
                model_id="gpt-4o-mini",
                connection_kwargs={"api_key": "sk-test", "base_url": None},
                llm_settings={"temperature": 0.2, "max_tokens": 128},
            )

        mocked.assert_called_once_with(
            model="gpt-4o-mini",
            api_key="sk-test",
            base_url=None,
            temperature=0.2,
            max_tokens=128,
        )

    async def test_gigachat_fetch_available_models(self):
        mock_llm = types.SimpleNamespace(
            aget_models=AsyncMock(
                return_value=types.SimpleNamespace(
                    data=[types.SimpleNamespace(id_="GigaChat", owned_by="sber")]
                )
            )
        )

        with patch("giga_agent.llm.gigachat.GigaChat", return_value=mock_llm):
            models = await GigaChatLLM.fetch_available_models(
                connector_type="gigachat",
                connector_settings={
                    "gigachat_api_type": "prod",
                    "gigachat_credentials": "token",
                },
            )

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "GigaChat")

    def test_gigachat_build_chat_model_from_kwargs(self):
        with patch("giga_agent.llm.gigachat.GigaChat", return_value=object()) as mocked:
            GigaChatLLM.build_chat_model_from_kwargs(
                model_id="GigaChat",
                connection_kwargs={"base_url": None, "credentials": "token"},
                llm_settings={"temperature": 0.4},
            )

        mocked.assert_called_once_with(
            model="GigaChat",
            base_url=None,
            credentials="token",
            temperature=0.4,
            max_tokens=1280000,
            profanity_check=False,
            timeout=60,
        )
