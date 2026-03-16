import json
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, patch

from giga_agent.modules.analyze_images.tool import analyze_image
from giga_agent.sandbox.base import ContentResult, RedirectResult
from PIL import Image


class AnalyzeImagesToolTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, owner_id: uuid.UUID):
        return types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}},
            tool_call_id="tool-call-1",
        )

    def _png_bytes(self) -> bytes:
        import io

        image = Image.new("RGB", (1, 1), (255, 0, 0))
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    async def test_analyze_image_happy_path(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="image analysis"),
            model_id="gpt-4o",
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.analyze_images.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(
                    object(),
                    ContentResult(data=self._png_bytes(), media_type="image/png"),
                )
            ),
        ), patch(
            "giga_agent.modules.analyze_images.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.analyze_images.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_path="/runs/test/image.png",
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "image analysis")
        self.assertEqual(payload["image_path"], "/runs/test/image.png")
        self.assertEqual(payload["model"], "gpt-4o")
        llm_runtime.analyze_image.assert_awaited_once_with(
            prompt="describe",
            image_bytes=ANY,
            mime_type="image/jpg",
        )
        sent_bytes = llm_runtime.analyze_image.await_args.kwargs["image_bytes"]
        self.assertTrue(sent_bytes.startswith(b"\xff\xd8"))

    async def test_analyze_image_raises_when_file_not_found(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.analyze_images.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
            AsyncMock(side_effect=ValueError("not found")),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "not found"):
                await analyze_image.coroutine(
                    image_path="/runs/missing.png",
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_raises_when_user_has_no_llm(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, llm_id=None)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.analyze_images.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(
                    object(),
                    ContentResult(data=self._png_bytes(), media_type="image/png"),
                )
            ),
        ), patch(
            "giga_agent.modules.analyze_images.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "llm_id"):
                await analyze_image.coroutine(
                    image_path="/runs/test/image.png",
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_raises_when_runtime_has_no_capability(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: False,
            model_id="model",
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.analyze_images.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(
                    object(),
                    ContentResult(data=self._png_bytes(), media_type="image/png"),
                )
            ),
        ), patch(
            "giga_agent.modules.analyze_images.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.analyze_images.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "не поддерживает"):
                await analyze_image.coroutine(
                    image_path="/runs/test/image.png",
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_downloads_redirect_content(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="analysis"),
            model_id="model",
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.analyze_images.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
            AsyncMock(return_value=(object(), RedirectResult(url="https://example.com/file"))),
        ), patch(
            "giga_agent.modules.analyze_images.tool._download_redirect_bytes",
            AsyncMock(return_value=(self._png_bytes(), "image/png")),
        ), patch(
            "giga_agent.modules.analyze_images.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.analyze_images.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_path="/runs/test/image.png",
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "analysis")
        llm_runtime.analyze_image.assert_awaited_once()
