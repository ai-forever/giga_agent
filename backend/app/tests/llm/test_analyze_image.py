import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.llm.base import BaseLLMRuntime
from giga_agent.llm.gigachat import GigaChatRuntime
from giga_agent.llm.openai import OpenAIRuntime


class _BaseRuntimeStub(BaseLLMRuntime):
    _llm_stub = None

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["openai"]

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector_type: str,
        connector_settings: dict,
    ) -> list:
        _ = connector_type, connector_settings
        return []

    def _llm(self):
        return self.__class__._llm_stub


class AnalyzeImageRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_runtime_analyze_image_sends_base64_data_url(self):
        llm_stub = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value=types.SimpleNamespace(text="ok"))
        )
        _BaseRuntimeStub._llm_stub = llm_stub
        runtime = _BaseRuntimeStub(
            connector=types.SimpleNamespace(), model_id="test-model"
        )

        result = await runtime.analyze_image(
            prompt="what is on this image",
            image_bytes=b"img-bytes",
            mime_type="image/jpeg",
        )

        self.assertEqual(result, "ok")
        llm_stub.ainvoke.assert_awaited_once()
        messages = llm_stub.ainvoke.await_args.args[0]
        self.assertEqual(messages[0].content[0]["type"], "text")
        self.assertEqual(messages[0].content[1]["type"], "image_url")
        self.assertTrue(
            messages[0]
            .content[1]["image_url"]["url"]
            .startswith("data:image/jpeg;base64,")
        )

    def test_openai_runtime_uses_base_implementation(self):
        self.assertIs(OpenAIRuntime.analyze_image, BaseLLMRuntime.analyze_image)

    async def test_gigachat_runtime_analyze_image_uses_uploaded_file(self):
        llm_stub = types.SimpleNamespace(
            aupload_file=AsyncMock(return_value=types.SimpleNamespace(id_="file-123")),
            ainvoke=AsyncMock(return_value=types.SimpleNamespace(text="analysis")),
        )
        runtime = GigaChatRuntime(connector=types.SimpleNamespace(), model_id="giga")
        with patch.object(GigaChatRuntime, "_llm", return_value=llm_stub):
            result = await runtime.analyze_image(
                prompt="describe image",
                image_bytes=b"raw-image",
                mime_type="image/png",
            )

        self.assertEqual(result, "analysis")
        llm_stub.aupload_file.assert_awaited_once()
        upload_args, upload_kwargs = llm_stub.aupload_file.await_args
        self.assertEqual(upload_kwargs["purpose"], "general")
        self.assertIsInstance(upload_args[0], tuple)

        llm_stub.ainvoke.assert_awaited_once()
        messages = llm_stub.ainvoke.await_args.args[0]
        attachments = messages[0].additional_kwargs["attachments"]
        self.assertEqual(attachments[0], "file-123")
