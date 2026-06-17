import json
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, patch

from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.modules.analyze_images.tool import analyze_image
from giga_agent.sandbox.base import ContentResult, RedirectResult
from PIL import Image


class AnalyzeImagesToolTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, owner_id: uuid.UUID, *, user=None, llm_runtime=None):
        config = {"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        if user is not None:
            resolver = RuntimeResolver(user)
            if llm_runtime is not None:
                resolver._cache["llm"] = llm_runtime
            config["configurable"]["runtime_resolver"] = resolver
        return types.SimpleNamespace(
            config=config,
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
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="image analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

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
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        runtime = self._runtime(owner_id, user=user)

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
        user = types.SimpleNamespace(id=owner_id, llm_id=None)
        runtime = self._runtime(owner_id, user=user)

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
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: False,
            model_id="model",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

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
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="analysis"),
            model_id="model",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

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

    async def test_analyze_image_converts_plotly_json_before_analysis(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="chart analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

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
                    ContentResult(
                        data=json.dumps(
                            {"data": [{"type": "bar", "x": ["A"], "y": [1]}], "layout": {}}
                        ).encode("utf-8"),
                        media_type="application/json",
                    ),
                )
            ),
        ), patch(
            "giga_agent.modules.analyze_images.tool._plotly_json_to_png_bytes",
            return_value=self._png_bytes(),
        ) as plotly_to_png:
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_path="/runs/test/chart.plotly.json",
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "chart analysis")
        plotly_to_png.assert_called_once()
        llm_runtime.analyze_image.assert_awaited_once_with(
            prompt="describe",
            image_bytes=ANY,
            mime_type="image/jpg",
        )

    async def test_analyze_image_raises_for_non_plotly_json(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        runtime = self._runtime(owner_id, user=user)

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
                    ContentResult(
                        data=json.dumps({"status": "ok"}).encode("utf-8"),
                        media_type="application/json",
                    ),
                )
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "Plotly JSON"):
                await analyze_image.coroutine(
                    image_path="/runs/test/data.json",
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_converts_plotly_json_by_path_when_mime_is_generic(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4())
        llm_runtime = types.SimpleNamespace(
            can_analyze_image=lambda: True,
            analyze_image=AsyncMock(return_value="chart analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

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
                    ContentResult(
                        data=json.dumps(
                            {"data": [{"type": "scatter", "x": [1], "y": [2]}], "layout": {}}
                        ).encode("utf-8"),
                        media_type="application/octet-stream",
                    ),
                )
            ),
        ), patch(
            "giga_agent.modules.analyze_images.tool._plotly_json_to_png_bytes",
            return_value=self._png_bytes(),
        ) as plotly_to_png:
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_path="/runs/test/chart.plotly.json",
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "chart analysis")
        plotly_to_png.assert_called_once()
