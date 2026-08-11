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
    def _runtime(
        self, owner_id: uuid.UUID, *, user=None, llm_runtime=None, fast_llm_runtime=None
    ):
        config = {"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        if user is not None:
            resolver = RuntimeResolver(user)
            if llm_runtime is not None:
                resolver._cache["llm"] = llm_runtime
            if fast_llm_runtime is not None:
                resolver._cache["fast_llm"] = fast_llm_runtime
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
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="image analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(data=self._png_bytes(), media_type="image/png"),
                    )
                ),
            ),
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_paths=["/runs/test/image.png"],
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "image analysis")
        self.assertEqual(payload["image_paths"], ["/runs/test/image.png"])
        self.assertEqual(payload["model"], "gpt-4o")
        llm_runtime.analyze_images.assert_awaited_once_with(
            prompt="describe",
            images=ANY,
        )
        sent_bytes = llm_runtime.analyze_images.await_args.kwargs["images"][0][
            "image_bytes"
        ]
        self.assertTrue(sent_bytes.startswith(b"\xff\xd8"))

    async def test_analyze_image_accepts_four_images_in_input_order(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="comparison"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)
        image_paths = [f"/runs/test/image-{index}.png" for index in range(4)]
        prepared_images = [
            {"image_bytes": f"image-{index}".encode(), "mime_type": "image/jpg"}
            for index in range(4)
        ]

        with patch(
            "giga_agent.modules.analyze_images.tool._prepare_image",
            new=AsyncMock(side_effect=prepared_images),
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_paths=image_paths,
                prompt="compare",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["image_paths"], image_paths)
        self.assertEqual(
            llm_runtime.analyze_images.await_args.kwargs["images"],
            prepared_images,
        )

    async def test_analyze_image_rejects_invalid_batch_size_before_loading(self):
        runtime = types.SimpleNamespace(config={}, tool_call_id="tool-call-1")

        with patch(
            "giga_agent.modules.analyze_images.tool._prepare_images",
            new=AsyncMock(),
        ) as prepare_images:
            assert analyze_image.coroutine is not None
            for image_paths in ([], [f"/runs/test/{index}.png" for index in range(5)]):
                with self.subTest(image_count=len(image_paths)):
                    with self.assertRaisesRegex(ValueError, "от 1 до 4"):
                        await analyze_image.coroutine(
                            image_paths=image_paths,
                            prompt="describe",
                            runtime=runtime,
                        )

        prepare_images.assert_not_awaited()

    async def test_analyze_image_raises_when_file_not_found(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        runtime = self._runtime(owner_id, user=user)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(side_effect=ValueError("not found")),
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, r"missing\.png.*not found"):
                await analyze_image.coroutine(
                    image_paths=["/runs/missing.png"],
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_raises_when_user_has_no_llm(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=None, fast_llm_id=None)
        runtime = self._runtime(owner_id, user=user)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(data=self._png_bytes(), media_type="image/png"),
                    )
                ),
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "не поддерживает"):
                await analyze_image.coroutine(
                    image_paths=["/runs/test/image.png"],
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_raises_when_runtime_has_no_capability(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: False,
            model_id="model",
        )
        # The tool falls back to fast_llm; seed it too so no capable LLM exists.
        fast_llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: False,
            model_id="fast-model",
        )
        runtime = self._runtime(
            owner_id,
            user=user,
            llm_runtime=llm_runtime,
            fast_llm_runtime=fast_llm_runtime,
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(data=self._png_bytes(), media_type="image/png"),
                    )
                ),
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "не поддерживает"):
                await analyze_image.coroutine(
                    image_paths=["/runs/test/image.png"],
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_downloads_redirect_content(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="analysis"),
            model_id="model",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        RedirectResult(url="https://example.com/file"),
                    )
                ),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.materialize_bounded",
                AsyncMock(return_value=(self._png_bytes(), False)),
            ),
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_paths=["/runs/test/image.png"],
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "analysis")
        llm_runtime.analyze_images.assert_awaited_once()

    async def test_analyze_image_prepares_url_sandbox_and_plotly_in_one_batch(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="mixed analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)
        image_paths = [
            "https://example.com/image.png",
            "/runs/test/image.png",
            "/runs/test/chart.plotly.json",
        ]

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool._download_image_bytes",
                AsyncMock(return_value=(self._png_bytes(), "image/png")),
            ) as download_image,
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    side_effect=[
                        (
                            object(),
                            ContentResult(
                                data=self._png_bytes(), media_type="image/png"
                            ),
                        ),
                        (
                            object(),
                            ContentResult(
                                data=b'{"data": [], "layout": {}}',
                                media_type="application/json",
                            ),
                        ),
                    ]
                ),
            ) as read_file,
            patch(
                "giga_agent.modules.analyze_images.tool._plotly_json_to_png_bytes",
                return_value=self._png_bytes(),
            ),
        ):
            assert analyze_image.coroutine is not None
            await analyze_image.coroutine(
                image_paths=image_paths,
                prompt="compare",
                runtime=runtime,
            )

        download_image.assert_awaited_once_with(url=image_paths[0])
        self.assertEqual(read_file.await_count, 2)
        images = llm_runtime.analyze_images.await_args.kwargs["images"]
        self.assertEqual(len(images), 3)
        self.assertTrue(all(image["mime_type"] == "image/jpg" for image in images))

    async def test_analyze_image_does_not_call_llm_when_one_image_fails(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

        with patch(
            "giga_agent.modules.analyze_images.tool._prepare_image",
            new=AsyncMock(
                side_effect=[
                    {"image_bytes": b"first", "mime_type": "image/jpg"},
                    ValueError("Не удалось подготовить изображение '/runs/bad.png'"),
                ]
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, r"bad\.png"):
                await analyze_image.coroutine(
                    image_paths=["/runs/good.png", "/runs/bad.png"],
                    prompt="compare",
                    runtime=runtime,
                )

        llm_runtime.analyze_images.assert_not_awaited()

    async def test_analyze_image_converts_plotly_json_before_analysis(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="chart analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(
                            data=json.dumps(
                                {
                                    "data": [{"type": "bar", "x": ["A"], "y": [1]}],
                                    "layout": {},
                                }
                            ).encode("utf-8"),
                            media_type="application/json",
                        ),
                    )
                ),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool._plotly_json_to_png_bytes",
                return_value=self._png_bytes(),
            ) as plotly_to_png,
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_paths=["/runs/test/chart.plotly.json"],
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "chart analysis")
        plotly_to_png.assert_called_once()
        llm_runtime.analyze_images.assert_awaited_once_with(
            prompt="describe",
            images=ANY,
        )

    async def test_analyze_image_raises_for_non_plotly_json(self):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        runtime = self._runtime(owner_id, user=user)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
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
            ),
        ):
            assert analyze_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "Plotly JSON"):
                await analyze_image.coroutine(
                    image_paths=["/runs/test/data.json"],
                    prompt="describe",
                    runtime=runtime,
                )

    async def test_analyze_image_converts_plotly_json_by_path_when_mime_is_generic(
        self,
    ):
        owner_id = uuid.uuid4()
        user = types.SimpleNamespace(id=owner_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        llm_runtime = types.SimpleNamespace(
            can_analyze_images=lambda: True,
            analyze_images=AsyncMock(return_value="chart analysis"),
            model_id="gpt-4o",
        )
        runtime = self._runtime(owner_id, user=user, llm_runtime=llm_runtime)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.modules.analyze_images.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(
                            data=json.dumps(
                                {
                                    "data": [{"type": "scatter", "x": [1], "y": [2]}],
                                    "layout": {},
                                }
                            ).encode("utf-8"),
                            media_type="application/octet-stream",
                        ),
                    )
                ),
            ),
            patch(
                "giga_agent.modules.analyze_images.tool._plotly_json_to_png_bytes",
                return_value=self._png_bytes(),
            ) as plotly_to_png,
        ):
            assert analyze_image.coroutine is not None
            message = await analyze_image.coroutine(
                image_paths=["/runs/test/chart.plotly.json"],
                prompt="describe",
                runtime=runtime,
            )

        payload = json.loads(message.content)
        self.assertEqual(payload["analysis"], "chart analysis")
        plotly_to_png.assert_called_once()
