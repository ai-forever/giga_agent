import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.modules.rag.tools import read_file
from giga_agent.sandbox.base import ContentResult, RedirectResult


class RagToolsTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self, owner_id: uuid.UUID):
        return types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}},
            tool_call_id="tool-call-1",
        )

    async def test_read_file_returns_numbered_text_content(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="doc.txt", size=12)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(file_record, ContentResult(data="hello world".encode("utf-8")))
            ),
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/doc.txt",
                runtime=runtime,
            )

        self.assertEqual(payload["file"], "doc.txt")
        self.assertEqual(payload["sandbox_path"], "/docs/doc.txt")
        self.assertEqual(payload["content"], "1|hello world")
        self.assertEqual(payload["total_lines"], 1)
        self.assertEqual(payload["returned_lines"], 1)
        self.assertEqual(payload["remaining_lines"], 0)
        self.assertFalse(payload["truncated"])
        self.assertIn("Достигнут конец файла", payload["next_read_hint"])

    async def test_read_file_respects_offset_and_limit(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="doc.txt", size=24)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(
                    file_record,
                    ContentResult(data="alpha\nbeta\ngamma\ndelta".encode("utf-8")),
                )
            ),
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/doc.txt",
                runtime=runtime,
                offset=2,
                limit=2,
            )

        self.assertEqual(payload["content"], "2|beta\n3|gamma")
        self.assertEqual(payload["total_lines"], 4)
        self.assertEqual(payload["returned_lines"], 2)
        self.assertEqual(payload["remaining_lines"], 1)
        self.assertTrue(payload["truncated"])
        self.assertIn("Файл еще имеет 1 строк", payload["next_read_hint"])
        self.assertIn("offset=4, limit=2", payload["next_read_hint"])

    async def test_read_file_downloads_redirect_content(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="doc.txt", size=12)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(return_value=(file_record, RedirectResult(url="https://example.com/file"))),
        ), patch(
            "giga_agent.modules.rag.tools._download_redirect_bytes",
            AsyncMock(return_value="redirect body".encode("utf-8")),
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/doc.txt",
                runtime=runtime,
            )

        self.assertEqual(payload["content"], "1|redirect body")
        self.assertFalse(payload["truncated"])

    async def test_read_file_extracts_pdf_text(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="doc.pdf", size=128)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(
                return_value=(
                    file_record,
                    ContentResult(data=b"%PDF-1.7...", media_type="application/pdf"),
                )
            ),
        ), patch(
            "giga_agent.modules.rag.tools._extract_pdf_text",
            return_value="pdf line one\npdf line two",
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/doc.pdf",
                runtime=runtime,
            )

        self.assertEqual(payload["content"], "1|pdf line one\n2|pdf line two")

    async def test_read_file_rejects_binary_content(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="doc.bin", size=2)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(return_value=(file_record, ContentResult(data=b"\xff\xfe"))),
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/doc.bin",
                runtime=runtime,
            )

        self.assertEqual(payload["error"], "Файл не является текстовым (бинарный формат)")
        self.assertIsNone(payload["content"])

    async def test_read_file_returns_empty_file_message(self):
        owner_id = uuid.uuid4()
        runtime = self._runtime(owner_id)
        file_record = types.SimpleNamespace(original_name="empty.txt", size=0)

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.rag.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.sandbox.manager.SandboxManager.read_file_by_path_for_user",
            AsyncMock(return_value=(file_record, ContentResult(data=b""))),
        ):
            assert read_file.coroutine is not None
            payload = await read_file.coroutine(
                sandbox_path="/docs/empty.txt",
                runtime=runtime,
            )

        self.assertEqual(payload["content"], "File is empty.")
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["total_lines"], 0)

    async def test_read_file_handles_missing_runtime(self):
        assert read_file.coroutine is not None
        payload = await read_file.coroutine(
            sandbox_path="/docs/doc.txt",
            runtime=None,
        )

        self.assertEqual(payload, {"error": "ToolRuntime is required", "content": None})
