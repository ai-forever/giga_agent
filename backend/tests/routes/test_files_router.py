import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.core.db import get_session
from giga_agent.routes.files import router
from giga_agent.sandbox.base import ContentResult, RedirectResult


class FilesRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield object()

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    def _file_obj(self, sandbox_path: str):
        original_name = (sandbox_path or "").rstrip("/").split("/")[-1] or "download.bin"
        return types.SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            provider_id=uuid.uuid4(),
            sandbox_path=sandbox_path,
            original_name=original_name,
            file_type="text",
            size=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def test_upload_happy_path(self):
        created = self._file_obj("/home/user/bucket/giga_agent/u/report.txt")

        with patch(
            "giga_agent.routes.files.SandboxManager.upload_file_for_user",
            AsyncMock(return_value=created),
        ) as mocked_upload:
            response = self.client.post(
                "/files/upload",
                files={"file": ("report.txt", b"hello", "text/plain")},
                data={"thread_id": "thread-42"},
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["sandbox_path"], "/home/user/bucket/giga_agent/u/report.txt")
        self.assertEqual(body["original_name"], "report.txt")
        self.assertEqual(body["file_type"], "text")
        self.assertEqual(body["size"], 5)
        mocked_upload.assert_awaited_once()
        kwargs = mocked_upload.await_args.kwargs
        self.assertEqual(kwargs["file_name"], "thread-42/report.txt")
        self.assertEqual(kwargs["file_type"], "text")

    def test_upload_infers_video_file_type(self):
        created = self._file_obj("/home/user/bucket/giga_agent/u/movie.mp4")
        created.file_type = "video"

        with patch(
            "giga_agent.routes.files.SandboxManager.upload_file_for_user",
            AsyncMock(return_value=created),
        ) as mocked_upload:
            response = self.client.post(
                "/files/upload",
                files={"file": ("movie.mp4", b"\x00\x00", "video/mp4")},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["file_type"], "video")
        mocked_upload.assert_awaited_once()
        self.assertEqual(mocked_upload.await_args.kwargs["file_type"], "video")

    def test_read_s3_file_returns_redirect(self):
        file_obj = self._file_obj("/home/user/bucket/giga_agent/u/report.txt")
        result = RedirectResult(url="https://signed.example.local/object")

        with patch(
            "giga_agent.routes.files.FileRepository.get_by_id_readable",
            AsyncMock(return_value=file_obj),
        ), patch(
            "giga_agent.routes.files.SandboxManager.read_file_for_user",
            AsyncMock(return_value=(file_obj, result)),
        ):
            response = self.client.get(
                f"/files/{file_obj.id}/content",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://signed.example.local/object")

    def test_read_s3_file_returns_json_redirect_instruction(self):
        file_obj = self._file_obj("/home/user/bucket/giga_agent/u/report.txt")
        result = RedirectResult(url="https://signed.example.local/object")

        with patch(
            "giga_agent.routes.files.FileRepository.get_by_id_readable",
            AsyncMock(return_value=file_obj),
        ), patch(
            "giga_agent.routes.files.SandboxManager.read_file_for_user",
            AsyncMock(return_value=(file_obj, result)),
        ):
            response = self.client.get(
                f"/files/{file_obj.id}/content",
                params={"redirect_result": "json"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("content-type", "").split(";")[0],
            "application/vnd.giga-agent.redirect+json",
        )
        body = response.json()
        self.assertEqual(body["kind"], "redirect")
        self.assertEqual(body["url"], "https://signed.example.local/object")

    def test_read_local_file_returns_stream(self):
        file_obj = self._file_obj("/tmp/local.bin")
        result = ContentResult(data=b"payload")

        with patch(
            "giga_agent.routes.files.FileRepository.get_by_id_readable",
            AsyncMock(return_value=file_obj),
        ), patch(
            "giga_agent.routes.files.SandboxManager.read_file_for_user",
            AsyncMock(return_value=(file_obj, result)),
        ):
            response = self.client.get(f"/files/{file_obj.id}/content")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"payload")
        self.assertIn("attachment; filename=\"local.bin\"", response.headers["content-disposition"])

    def test_read_foreign_file_returns_403(self):
        file_id = uuid.uuid4()
        with patch(
            "giga_agent.routes.files.FileRepository.get_by_id_readable",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.files.FileRepository.get_by_id",
            AsyncMock(return_value=self._file_obj("/tmp/foreign.txt")),
        ):
            response = self.client.get(f"/files/{file_id}/content")

        self.assertEqual(response.status_code, 403)

    def test_read_missing_file_returns_404(self):
        file_id = uuid.uuid4()
        with patch(
            "giga_agent.routes.files.FileRepository.get_by_id_readable",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.files.FileRepository.get_by_id",
            AsyncMock(return_value=None),
        ):
            response = self.client.get(f"/files/{file_id}/content")

        self.assertEqual(response.status_code, 404)

    def test_read_by_path_returns_redirect(self):
        file_obj = self._file_obj("/home/user/bucket/giga_agent/u/report.txt")
        result = RedirectResult(url="https://signed.example.local/by-path")
        with patch(
            "giga_agent.routes.files.FileRepository.get_by_path_readable",
            AsyncMock(return_value=file_obj),
        ), patch(
            "giga_agent.routes.files.SandboxManager.read_file_for_user",
            AsyncMock(return_value=(file_obj, result)),
        ):
            response = self.client.get(
                "/files/content/by-path",
                params={"path": "/home/user/bucket/giga_agent/u/report.txt"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://signed.example.local/by-path")

    def test_read_by_path_returns_json_redirect_instruction(self):
        file_obj = self._file_obj("/home/user/bucket/giga_agent/u/report.txt")
        result = RedirectResult(url="https://signed.example.local/by-path")
        with patch(
            "giga_agent.routes.files.FileRepository.get_by_path_readable",
            AsyncMock(return_value=file_obj),
        ), patch(
            "giga_agent.routes.files.SandboxManager.read_file_for_user",
            AsyncMock(return_value=(file_obj, result)),
        ):
            response = self.client.get(
                "/files/content/by-path",
                params={
                    "path": "/home/user/bucket/giga_agent/u/report.txt",
                    "redirect_result": "json",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("content-type", "").split(";")[0],
            "application/vnd.giga-agent.redirect+json",
        )
        body = response.json()
        self.assertEqual(body["kind"], "redirect")
        self.assertEqual(body["url"], "https://signed.example.local/by-path")

    def test_read_by_path_missing_returns_404(self):
        with patch(
            "giga_agent.routes.files.FileRepository.get_by_path_readable",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.routes.files.FileRepository.get_by_path_any_owner",
            AsyncMock(return_value=None),
        ):
            response = self.client.get(
                "/files/content/by-path",
                params={"path": "/missing/file.txt"},
            )

        self.assertEqual(response.status_code, 404)

    def test_delete_file_calls_manager(self):
        file_id = uuid.uuid4()
        with patch(
            "giga_agent.routes.files.SandboxManager.delete_file_for_user",
            AsyncMock(return_value=None),
        ) as mocked_delete:
            response = self.client.delete(f"/files/{file_id}")

        self.assertEqual(response.status_code, 204)
        mocked_delete.assert_awaited_once()
