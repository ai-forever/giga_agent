import unittest

from giga_agent.modules.rag.services.document_processor import SUPPORTED_MIMETYPES, process_document


class _DummyUploadFile:
    def __init__(self, *, filename: str, content_type: str, content: bytes):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


class RagDocumentProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_document_sets_start_and_end_index(self) -> None:
        text = (
            "Привет мир!\n"
            "Это тестовый документ для проверки start_index/end_index.\n"
            "Он должен корректно биться на чанки."
        )
        dummy = _DummyUploadFile(
            filename="test.txt",
            content_type="text/plain",
            content=text.encode("utf-8"),
        )

        file_id, full_text, docs = await process_document(dummy, metadata={"name": "test.txt"})

        self.assertTrue(file_id)
        self.assertEqual(full_text, text)
        self.assertGreater(len(docs), 0)

        for d in docs:
            md = d.metadata or {}
            self.assertIn("start_index", md)
            self.assertIn("end_index", md)
            self.assertEqual(md.get("file_id"), file_id)

            start = int(md["start_index"])
            end = int(md["end_index"])
            self.assertGreaterEqual(start, 0)
            self.assertGreater(end, start)
            self.assertLessEqual(end, len(full_text))
            self.assertEqual(full_text[start:end], d.page_content)

    async def test_process_markdown_document(self) -> None:
        md_text = "# Заголовок\n\nТекст параграфа с **жирным** и *курсивом*.\n\n- Пункт 1\n- Пункт 2\n"
        dummy = _DummyUploadFile(
            filename="readme.md",
            content_type="text/markdown",
            content=md_text.encode("utf-8"),
        )

        file_id, full_text, docs = await process_document(dummy)

        self.assertTrue(file_id)
        self.assertEqual(full_text, md_text.strip())
        self.assertGreater(len(docs), 0)

    async def test_process_markdown_with_octet_stream_fallback(self) -> None:
        md_text = "# Test\n\nContent here.\n"
        dummy = _DummyUploadFile(
            filename="notes.md",
            content_type="application/octet-stream",
            content=md_text.encode("utf-8"),
        )

        file_id, full_text, docs = await process_document(dummy)

        self.assertTrue(file_id)
        self.assertEqual(full_text, md_text.strip())
        self.assertGreater(len(docs), 0)

    def test_markdown_mimetypes_in_supported_list(self) -> None:
        self.assertIn("text/markdown", SUPPORTED_MIMETYPES)
        self.assertIn("text/x-markdown", SUPPORTED_MIMETYPES)

