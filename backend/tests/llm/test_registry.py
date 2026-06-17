import types
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401
from giga_agent.conf import reset_settings_cache
from giga_agent.connectors.openai import OpenAIConnector
from giga_agent.connectors.gigachat import GigaChatConnector
from giga_agent.llm.gigachat import GigaChatRuntime
from giga_agent.llm.openai import OpenAIRuntime
from giga_agent.llm.registry import LLMRegistry


class LLMRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_settings_cache()

    def tearDown(self) -> None:
        reset_settings_cache()

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
        token_cache_mock = AsyncMock(return_value="tok")

        with patch(
            "giga_agent.llm.gigachat.get_gigachat_access_token_cached",
            token_cache_mock,
        ), patch("giga_agent.llm.gigachat.GigaChat", return_value=mock_llm) as mocked_llm:
            connector = GigaChatConnector(
                gigachat_api_type="prod",
                gigachat_credentials="token",
            )
            models = await GigaChatRuntime.fetch_available_models(
                connector=connector,
            )

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "GigaChat")
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

    async def test_gigachat_fetch_available_models_skips_access_token_when_flag_enabled(self):
        mock_llm = types.SimpleNamespace(
            aget_models=AsyncMock(
                return_value=types.SimpleNamespace(
                    data=[types.SimpleNamespace(id_="GigaChat", owned_by="sber")]
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
                "giga_agent.llm.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch("giga_agent.llm.gigachat.GigaChat", return_value=mock_llm) as mocked_llm:
                connector = GigaChatConnector(
                    gigachat_api_type="prod",
                    gigachat_credentials="token",
                )
                models = await GigaChatRuntime.fetch_available_models(
                    connector=connector,
                )

        self.assertEqual(len(models), 1)
        token_cache_mock.assert_not_awaited()
        mocked_llm.assert_called_once_with(
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            streaming=True,
            verify_ssl_certs=False,
        )

    async def test_gigachat_runtime_builder_skips_access_token_when_flag_enabled(self):
        token_cache_mock = AsyncMock(return_value="tok")

        with patch.dict(
            "os.environ",
            {"GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN": "1"},
            clear=False,
        ):
            reset_settings_cache()
            with patch(
                "giga_agent.llm.gigachat.get_gigachat_access_token_cached",
                token_cache_mock,
            ), patch("giga_agent.llm.gigachat.GigaChat", return_value=object()) as mocked_llm:
                runtime = GigaChatRuntime(
                    connector=GigaChatConnector(
                        gigachat_api_type="prod",
                        gigachat_credentials="token",
                    ),
                    model_id="GigaChat",
                )
                await runtime.get_llm()

        token_cache_mock.assert_not_awaited()
        mocked_llm.assert_called_once_with(
            model="GigaChat",
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            credentials="token",
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            max_tokens=1280000,
            profanity_check=False,
            streaming=True,
            timeout=60,
        )

    async def test_gigachat_runtime_enables_streaming(self):
        mock_llm = types.SimpleNamespace()
        with patch(
            "giga_agent.llm.gigachat.get_gigachat_access_token_cached",
            AsyncMock(return_value="tok"),
        ), patch("giga_agent.llm.gigachat.GigaChat", return_value=mock_llm) as mocked_ctor:
            connector = GigaChatConnector(
                gigachat_api_type="prod",
                gigachat_credentials="token",
            )
            runtime = GigaChatRuntime(connector=connector, model_id="GigaChat")
            llm = await runtime.get_llm()

        self.assertIs(llm, mock_llm)
        self.assertTrue(mocked_ctor.call_args.kwargs["streaming"])
