import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from giga_agent.modules.subagents_legacy.uploads import (
    build_tool_message,
    resolve_upload_prefix,
    upload_files_for_runtime_user,
)
from giga_agent.sandbox.manager import UploadBatchResult


def _file_payload(path: str) -> dict:
    now = datetime.now(timezone.utc)
    original_name = (path or "").rstrip("/").split("/")[-1] or "download.bin"
    return {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "provider_id": uuid.uuid4(),
        "sandbox_path": path,
        "original_name": original_name,
        "size": 12,
        "file_type": "text",
        "created_at": now,
        "updated_at": now,
    }


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class SubagentsLegacyUploadsTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_upload_prefix_uses_thread_id(self):
        runtime = types.SimpleNamespace(
            config={"configurable": {"thread_id": "thread-1"}}
        )
        self.assertEqual(resolve_upload_prefix(runtime), "thread-1")

    def test_build_tool_message_contains_attachments(self):
        runtime = types.SimpleNamespace(tool_call_id="call-1")
        from giga_agent.models.file import FileResponse

        msg = build_tool_message(
            runtime,
            tool_name="test_tool",
            payload={"ok": True},
            attachments=[FileResponse.model_validate(_file_payload("runs/a.txt"))],
        )
        self.assertEqual(msg.tool_call_id, "call-1")
        self.assertEqual(msg.additional_kwargs["tool_name"], "test_tool")
        self.assertEqual(len(msg.additional_kwargs["tool_attachments"]), 1)

    async def test_upload_files_uses_sandbox_manager(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={
                "configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}
            }
        )
        fake_manager = types.SimpleNamespace(
            upload_files_for_user=AsyncMock(
                return_value=UploadBatchResult(
                    files=[_file_payload("runs/result.txt")],
                    errors=[],
                )
            )
        )
        with (
            patch(
                "giga_agent.modules.subagents_legacy.uploads.get_session_factory",
                AsyncMock(return_value=lambda: _FakeSessionCtx()),
            ),
            patch(
                "giga_agent.modules.subagents_legacy.uploads.SandboxManager",
                return_value=fake_manager,
            ),
        ):
            files = await upload_files_for_runtime_user(
                runtime,
                files=[
                    {
                        "file_name": "runs/result.txt",
                        "file_type": "text",
                        "content": b"hello",
                    }
                ],
            )

        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].sandbox_path, "runs/result.txt")
        fake_manager.upload_files_for_user.assert_awaited_once()
