import types
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401
from giga_agent.embeddings.base import BaseEmbeddingRuntime
from giga_agent.embeddings.gigachat import GigaChatEmbeddingRuntime
from giga_agent.embeddings.openai import OpenAIEmbeddingRuntime
from giga_agent.embeddings.registry import EmbeddingRegistry


class EmbeddingRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_contains_expected_types(self):
        types_ = EmbeddingRegistry.available_types()
        self.assertIn("openai", types_)
        self.assertIn("gigachat", types_)

    def test_supported_connector_types(self):
        self.assertEqual(OpenAIEmbeddingRuntime.supported_connector_types(), ["openai"])
        self.assertEqual(GigaChatEmbeddingRuntime.supported_connector_types(), ["gigachat"])

    async def test_openai_fetch_available_models_returns_empty_by_default(self):
        models = await OpenAIEmbeddingRuntime.fetch_available_models(
            connector_type="openai",
            connector_settings={"api_key": "sk-test"},
        )
        self.assertEqual(models, [])

    async def test_base_fetch_available_models_returns_empty(self):
        class _RuntimeStub(BaseEmbeddingRuntime):
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

            @classmethod
            def build_embeddings_from_kwargs(
                cls,
                *,
                model_id: str,
                connection_kwargs: dict[str, object],
                embedding_settings: dict[str, object] | None = None,
            ):
                _ = model_id, connection_kwargs, embedding_settings
                return object()

        models = await _RuntimeStub.fetch_available_models(
            connector_type="openai",
            connector_settings={"api_key": "sk-test"},
        )
        self.assertEqual(models, [])

    def test_openai_build_embeddings_from_kwargs(self):
        with patch(
            "giga_agent.embeddings.openai.OpenAIEmbeddings",
            return_value=object(),
        ) as mocked:
            OpenAIEmbeddingRuntime.build_embeddings_from_kwargs(
                model_id="text-embedding-3-small",
                connection_kwargs={
                    "api_key": "sk-test",
                    "base_url": "https://api.openai.com/v1",
                },
                embedding_settings={"dimensions": 512, "chunk_size": 256},
            )

        mocked.assert_called_once_with(
            model="text-embedding-3-small",
            openai_api_key="sk-test",
            openai_api_base="https://api.openai.com/v1",
            dimensions=512,
            chunk_size=256,
        )

    async def test_gigachat_fetch_available_models_returns_all_sorted(self):
        mock_llm = types.SimpleNamespace(
            aget_models=AsyncMock(
                return_value=types.SimpleNamespace(
                    data=[
                        types.SimpleNamespace(id_="GigaChat", owned_by="sber"),
                        types.SimpleNamespace(id_="EmbeddingsGigaR", owned_by="sber"),
                    ]
                )
            )
        )

        with patch("giga_agent.embeddings.gigachat.GigaChat", return_value=mock_llm):
            models = await GigaChatEmbeddingRuntime.fetch_available_models(
                connector_type="gigachat",
                connector_settings={
                    "gigachat_api_type": "prod",
                    "gigachat_credentials": "token",
                },
            )

        self.assertEqual([item.id for item in models], ["EmbeddingsGigaR", "GigaChat"])

    def test_gigachat_build_embeddings_from_kwargs(self):
        with patch(
            "giga_agent.embeddings.gigachat.GigaChatEmbeddings",
            return_value=object(),
        ) as mocked:
            GigaChatEmbeddingRuntime.build_embeddings_from_kwargs(
                model_id="EmbeddingsGigaR",
                connection_kwargs={
                    "base_url": None,
                    "credentials": "token",
                    "scope": "GIGACHAT_API_PERS",
                    "verify_ssl_certs": False,
                },
                embedding_settings={"timeout": 40.0},
            )

        mocked.assert_called_once_with(
            model="EmbeddingsGigaR",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            timeout=40.0,
        )
