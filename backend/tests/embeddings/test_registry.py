import types
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401
from giga_agent.conf import reset_settings_cache
from giga_agent.connectors.gigachat import GigaChatConnector
from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.embeddings.base import BaseEmbeddingRuntime
from giga_agent.embeddings.gigachat import GigaChatEmbeddingRuntime
from giga_agent.embeddings.openai import OpenAIEmbeddingRuntime
from giga_agent.embeddings.registry import EmbeddingRegistry


class EmbeddingRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_settings_cache()

    def tearDown(self) -> None:
        reset_settings_cache()

    def test_registry_contains_expected_types(self):
        types_ = EmbeddingRegistry.available_types()
        self.assertIn("openai", types_)
        self.assertIn("gigachat", types_)

    def test_supported_connector_types(self):
        self.assertEqual(OpenAIEmbeddingRuntime.supported_connector_types(), ["openai"])
        self.assertEqual(GigaChatEmbeddingRuntime.supported_connector_types(), ["gigachat"])

    async def test_openai_fetch_available_models_returns_empty_by_default(self):
        models = await OpenAIEmbeddingRuntime.fetch_available_models(
            connector=OpenAIConnector(api_key="sk-test"),
        )
        self.assertEqual(models, [])

    async def test_base_fetch_available_models_returns_empty(self):
        class _RuntimeStub(BaseEmbeddingRuntime):
            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

            async def _create_embeddings(self):
                return object()

        models = await _RuntimeStub.fetch_available_models(
            connector=OpenAIConnector(api_key="sk-test"),
        )
        self.assertEqual(models, [])

    async def test_openai_embeddings_instance_builder(self):
        connector = OpenAIConnector(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        )
        with patch(
            "giga_agent.embeddings.openai.OpenAIEmbeddings",
            return_value=object(),
        ) as mocked:
            runtime = OpenAIEmbeddingRuntime(
                connector=connector,
                model_id="text-embedding-3-small",
                vector_size=512,
                dimensions=512,
                chunk_size=256,
            )
            await runtime.get_embeddings()

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
        token_cache_mock = AsyncMock(return_value="tok")

        with patch(
            "giga_agent.embeddings.gigachat.get_gigachat_access_token_cached",
            token_cache_mock,
        ), patch(
            "giga_agent.embeddings.gigachat.GigaChat",
            return_value=mock_llm,
        ) as mocked_llm:
            connector = GigaChatConnector(
                gigachat_api_type="prod",
                gigachat_credentials="token",
            )
            models = await GigaChatEmbeddingRuntime.fetch_available_models(
                connector=connector,
            )

        self.assertEqual([item.id for item in models], ["EmbeddingsGigaR", "GigaChat"])
        token_cache_mock.assert_awaited_once_with(connector)
        mocked_llm.assert_called_once_with(
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            streaming=True,
            access_token="tok",
        )

    async def test_gigachat_embeddings_instance_builder(self):
        connector = GigaChatConnector(
            gigachat_api_type="prod",
            gigachat_credentials="token",
            gigachat_scope="GIGACHAT_API_PERS",
        )
        with patch(
            "giga_agent.embeddings.gigachat.GigaChatEmbeddings",
            return_value=object(),
        ) as mocked, patch(
            "giga_agent.embeddings.gigachat.get_gigachat_access_token_cached",
            AsyncMock(return_value="tok"),
        ):
            runtime = GigaChatEmbeddingRuntime(
                connector=connector,
                model_id="EmbeddingsGigaR",
                vector_size=1024,
                timeout=40.0,
            )
            await runtime.get_embeddings()

        mocked.assert_called_once_with(
            model="EmbeddingsGigaR",
            base_url='https://gigachat.devices.sberbank.ru/api/v1',
            credentials="token",
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            timeout=40.0,
            access_token="tok",
        )

    async def test_gigachat_fetch_available_models_skips_access_token_when_flag_enabled(self):
        mock_llm = types.SimpleNamespace(
            aget_models=AsyncMock(
                return_value=types.SimpleNamespace(
                    data=[types.SimpleNamespace(id_="EmbeddingsGigaR", owned_by="sber")]
                )
            )
        )
        token_cache_mock = AsyncMock(return_value="tok")

        with patch.dict(
            "os.environ",
            {"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"},
            clear=False,
        ):
            reset_settings_cache()
            with patch(
                "giga_agent.embeddings.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch(
                "giga_agent.embeddings.gigachat.GigaChat",
                return_value=mock_llm,
            ) as mocked_llm:
                connector = GigaChatConnector(
                    gigachat_api_type="prod",
                    gigachat_credentials="token",
                )
                models = await GigaChatEmbeddingRuntime.fetch_available_models(
                    connector=connector,
                )

        self.assertEqual([item.id for item in models], ["EmbeddingsGigaR"])
        token_cache_mock.assert_not_awaited()
        mocked_llm.assert_called_once_with(
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            streaming=True,
            verify_ssl_certs=False,
        )

    async def test_gigachat_embeddings_builder_skips_access_token_when_flag_enabled(self):
        token_cache_mock = AsyncMock(return_value="tok")

        with patch.dict(
            "os.environ",
            {"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"},
            clear=False,
        ):
            reset_settings_cache()
            with patch(
                "giga_agent.embeddings.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch(
                "giga_agent.embeddings.gigachat.GigaChatEmbeddings",
                return_value=object(),
            ) as mocked:
                runtime = GigaChatEmbeddingRuntime(
                    connector=GigaChatConnector(
                        gigachat_api_type="prod",
                        gigachat_credentials="token",
                        gigachat_scope="GIGACHAT_API_PERS",
                    ),
                    model_id="EmbeddingsGigaR",
                    vector_size=1024,
                    timeout=40.0,
                )
                await runtime.get_embeddings()

        token_cache_mock.assert_not_awaited()
        mocked.assert_called_once_with(
            model="EmbeddingsGigaR",
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            timeout=40.0,
        )
