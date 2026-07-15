import base64
import json
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.nano_banana.generator import NanoBananaImageGen
from giga_agent.generators.image.nano_banana.tool import gen_image
from giga_agent.sandbox.base import ContentResult


class NanoBananaToolTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, owner_id: uuid.UUID):
        return types.SimpleNamespace(
            config={
                "configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}
            },
            tool_call_id="tool-call-1",
        )

    async def test_gen_image_reads_input_images_and_uploads_result(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, image_generator_id=uuid.uuid4())
        generator = NanoBananaImageGen(api_key="test-key")
        uploaded_file = types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=owner_id,
            provider_id=uuid.uuid4(),
            sandbox_path="/runs/thread/images/generated.png",
            original_name="generated.png",
            size=15,
            file_type="image",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        resolver = types.SimpleNamespace(
            user=user,
            has_image_generator=True,
            get_image_generator=AsyncMock(return_value=generator),
        )

        with (
            patch(
                "giga_agent.generators.image.nano_banana.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
                return_value=resolver,
            ),
            patch(
                "giga_agent.generators.image.nano_banana.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(data=b"input-image", media_type="image/png"),
                    )
                ),
            ),
            patch(
                "giga_agent.generators.image.nano_banana.tool.SandboxManager.upload_files_for_user",
                AsyncMock(return_value=types.SimpleNamespace(files=[uploaded_file])),
            ) as mocked_upload,
            patch.object(
                NanoBananaImageGen,
                "generate_image",
                new=AsyncMock(
                    return_value=base64.b64encode(b"generated-image").decode("ascii")
                ),
            ) as mocked_generate,
        ):
            assert gen_image.coroutine is not None
            message = await gen_image.coroutine(
                prompt="restyle this image",
                runtime=runtime,
                input_paths=["attachment:/runs/ref.png"],
                aspect_ratio="1:1",
            )

        payload = json.loads(message.content)
        self.assertIn("/runs/thread/images/generated.png", payload["output"])
        self.assertEqual(message.additional_kwargs["tool_name"], "gen_image")
        self.assertEqual(
            mocked_generate.await_args.args,
            ("restyle this image", None, None),
        )
        kwargs = mocked_generate.await_args.kwargs
        self.assertEqual(kwargs["aspect_ratio"], "1:1")
        self.assertEqual(len(kwargs["input_images"]), 1)
        self.assertEqual(kwargs["input_images"][0]["mime_type"], "image/png")
        self.assertEqual(
            kwargs["input_images"][0]["content_b64"],
            base64.b64encode(b"input-image").decode("ascii"),
        )
        mocked_upload.assert_awaited_once()

    async def test_gen_image_rejects_non_image_inputs(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        user = types.SimpleNamespace(id=owner_id, image_generator_id=uuid.uuid4())
        generator = NanoBananaImageGen(api_key="test-key")

        @asynccontextmanager
        async def _session_context():
            yield object()

        resolver = types.SimpleNamespace(
            user=user,
            has_image_generator=True,
            get_image_generator=AsyncMock(return_value=generator),
        )

        with (
            patch(
                "giga_agent.generators.image.nano_banana.tool.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
                return_value=resolver,
            ),
            patch(
                "giga_agent.generators.image.nano_banana.tool.SandboxManager.read_file_by_path_for_user",
                AsyncMock(
                    return_value=(
                        object(),
                        ContentResult(data=b"not-image", media_type="text/plain"),
                    )
                ),
            ),
        ):
            assert gen_image.coroutine is not None
            with self.assertRaisesRegex(ValueError, "не является изображением"):
                await gen_image.coroutine(
                    prompt="restyle this image",
                    runtime=runtime,
                    input_paths=["/runs/ref.txt"],
                )
