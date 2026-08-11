import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.connectors.base import BaseConnector
from giga_agent.llm.base import BaseLLMRuntime
from giga_agent.llm.deepseek import DeepSeekRuntime
from giga_agent.llm.gigachat import GigaChatRuntime
from giga_agent.llm.openai import OpenAIRuntime


class _ConnectorStub(BaseConnector):
    def get_connection_kwargs(self):
        return {}

    def get_api_object(self):
        return object()


class _BaseRuntimeStub(BaseLLMRuntime):
    _llm_stub = None

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["openai"]

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector: BaseConnector,
    ) -> list:
        _ = connector
        return []

    async def _create_llm(self):
        return self.__class__._llm_stub


class AnalyzeImageRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_runtime_analyze_images_sends_ordered_data_urls(self):
        llm_stub = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value=types.SimpleNamespace(text="ok")),
            with_config=lambda **kwargs: llm_stub,
        )
        _BaseRuntimeStub._llm_stub = llm_stub
        runtime = _BaseRuntimeStub(connector=_ConnectorStub(), model_id="test-model")

        result = await runtime.analyze_images(
            prompt="compare these images",
            images=[
                {"image_bytes": b"first", "mime_type": "image/jpeg"},
                {"image_bytes": b"second", "mime_type": "image/png"},
            ],
        )

        self.assertEqual(result, "ok")
        llm_stub.ainvoke.assert_awaited_once()
        messages = llm_stub.ainvoke.await_args.args[0]
        content = messages[0].content
        self.assertEqual(content[0], {"type": "text", "text": "compare these images"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[2]["type"], "image_url")
        self.assertTrue(
            content[1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"
            )
        )
        self.assertTrue(
            content[2]["image_url"]["url"].startswith("data:image/png;base64,")
        )

    def test_openai_runtime_uses_base_implementation(self):
        self.assertIs(OpenAIRuntime.analyze_images, BaseLLMRuntime.analyze_images)

    def test_deepseek_runtime_does_not_support_image_analysis(self):
        runtime = DeepSeekRuntime(connector=_ConnectorStub(), model_id="deepseek")
        self.assertFalse(runtime.can_analyze_images())

    async def test_gigachat_runtime_analyze_images_uses_ordered_attachments(self):
        llm_stub = types.SimpleNamespace(
            aupload_file=AsyncMock(
                side_effect=[
                    types.SimpleNamespace(id_="file-1"),
                    types.SimpleNamespace(id_="file-2"),
                ]
            ),
            ainvoke=AsyncMock(return_value=types.SimpleNamespace(text="analysis")),
            with_config=lambda **kwargs: llm_stub,
        )
        runtime = GigaChatRuntime(connector=_ConnectorStub(), model_id="giga")
        with patch.object(GigaChatRuntime, "get_llm", AsyncMock(return_value=llm_stub)):
            result = await runtime.analyze_images(
                prompt="compare images",
                images=[
                    {"image_bytes": b"first", "mime_type": "image/png"},
                    {"image_bytes": b"second", "mime_type": "image/jpeg"},
                ],
            )

        self.assertEqual(result, "analysis")
        self.assertEqual(llm_stub.aupload_file.await_count, 2)
        for call in llm_stub.aupload_file.await_args_list:
            self.assertEqual(call.kwargs["purpose"], "general")
            self.assertIsInstance(call.args[0], tuple)

        llm_stub.ainvoke.assert_awaited_once()
        messages = llm_stub.ainvoke.await_args.args[0]
        self.assertEqual(
            messages[0].additional_kwargs["attachments"],
            ["file-1", "file-2"],
        )
