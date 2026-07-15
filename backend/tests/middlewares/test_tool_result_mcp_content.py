import base64
import unittest
import uuid
from unittest import mock

from giga_agent.middlewares import tool_result
from giga_agent.middlewares.tool_result import (
    _resolve_resource_meta,
    process_mcp_content,
)

_OWNER = uuid.uuid4()


def _audio_resource(blob: bytes, mime: str = "audio/mpeg") -> dict:
    return {
        "type": "resource",
        "resource": {
            "uri": "elevenlabs://speech.mp3",
            "mimeType": mime,
            "blob": base64.b64encode(blob).decode("utf-8"),
        },
    }


class ResolveResourceMetaTests(unittest.TestCase):
    def test_media_kinds_from_mime(self) -> None:
        self.assertEqual(_resolve_resource_meta("audio/mpeg"), ("audio", ".mp3"))
        self.assertEqual(_resolve_resource_meta("image/png"), ("image", ".png"))
        self.assertEqual(_resolve_resource_meta("video/mp4"), ("video", ".mp4"))

    def test_non_media_is_other(self) -> None:
        ft, ext = _resolve_resource_meta("application/json")
        self.assertEqual(ft, "other")
        self.assertTrue(ext.startswith("."))
        self.assertEqual(
            _resolve_resource_meta("application/x-bogus"), ("other", ".bin")
        )


class ProcessMcpResourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Avoid DB/config plumbing — pin owner/thread and capture uploads.
        self._owner_patch = mock.patch.object(
            tool_result, "_resolve_owner_id", return_value=_OWNER
        )
        self._thread_patch = mock.patch.object(
            tool_result, "_resolve_thread_id", return_value="thread1"
        )
        self._owner_patch.start()
        self._thread_patch.start()

        self.captured: list[dict] = []

        async def fake_upload(*, owner_id, files):
            self.captured = list(files)
            # Echo back as "uploaded" files so attachments get built.
            return [
                {"sandbox_path": f"/s/{f['file_name']}", "file_type": f["file_type"]}
                for f in files
            ]

        self._upload_patch = mock.patch.object(
            tool_result, "_upload_files_for_owner", side_effect=fake_upload
        )
        self._upload_mock = self._upload_patch.start()

    async def asyncTearDown(self) -> None:
        self._owner_patch.stop()
        self._thread_patch.stop()
        self._upload_patch.stop()

    async def test_audio_embedded_resource_uploaded(self) -> None:
        raw = b"ID3fakemp3bytes"
        _data, attachments, message = await process_mcp_content(
            [_audio_resource(raw)], config={}
        )
        self.assertEqual(len(self.captured), 1)
        spec = self.captured[0]
        self.assertEqual(spec["file_type"], "audio")
        self.assertEqual(spec["content"], raw)
        self.assertTrue(spec["file_name"].endswith(".mp3"))
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["file_type"], "audio")
        self.assertIn(".mp3", message)

    async def test_html_resource_not_persisted(self) -> None:
        html_res = {
            "type": "resource",
            "resource": {
                "uri": "ui://app/mcp-app.html",
                "mimeType": "text/html;profile=mcp-app",
                "text": "<!DOCTYPE html><html></html>",
            },
        }
        _data, attachments, _msg = await process_mcp_content([html_res], config={})
        # UI/HTML widgets must never hit the sandbox.
        self.assertEqual(self.captured, [])
        self._upload_mock.assert_not_awaited()
        self.assertEqual(attachments, [])

    async def test_text_resource_becomes_result(self) -> None:
        text_res = {
            "type": "resource",
            "resource": {"uri": "x://a.txt", "mimeType": "text/plain", "text": "hi"},
        }
        data, attachments, _msg = await process_mcp_content([text_res], config={})
        self.assertEqual(data, "hi")
        self.assertEqual(attachments, [])
        self._upload_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
