import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from botocore.exceptions import ClientError

from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
from giga_agent.sandbox.e2b import E2BSandbox


class _FakeS3Client:
    def __init__(self, existing_keys: set[str] | None = None, content_length: int = 100):
        self.existing_keys = existing_keys or set()
        self.put_calls: list[dict] = []
        self._content_length = content_length

    async def head_object(self, Bucket: str, Key: str):
        if Key in self.existing_keys:
            return {"Bucket": Bucket, "Key": Key, "ContentLength": self._content_length}
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    async def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ETag": "etag"}

    def generate_presigned_url(self, operation_name: str, Params: dict, ExpiresIn: int):
        return (
            f"https://example.local/{Params['Bucket']}/{Params['Key']}"
            f"?op={operation_name}&expires={ExpiresIn}"
        )


class _FakeClientCtx:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, client):
        self._client = client

    def client(self, *args, **kwargs):
        return _FakeClientCtx(self._client)


class E2BFileOpsTests(unittest.IsolatedAsyncioTestCase):
    def _sandbox(self) -> E2BSandbox:
        return E2BSandbox(
            api_key="key",
            s3_bucket="bucket",
            s3_endpoint="https://s3.example.local",
            s3_region="ru-central-1",
            aws_access_key_id="ak",
            aws_secret_access_key="sk",
        )

    async def test_uniquify_s3_key_adds_random_suffix(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = await sandbox._uniquify_s3_key(owner_id=owner_id, file_name="report.txt")

        self.assertEqual(key, f"giga_agent/{owner_id}/report--ABCDEFGH.txt")

    async def test_uniquify_s3_key_adds_suffix_before_plotly_json_extension(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = await sandbox._uniquify_s3_key(
                owner_id=owner_id,
                file_name="chart.plotly.json",
            )

        self.assertEqual(key, f"giga_agent/{owner_id}/chart--ABCDEFGH.plotly.json")

    async def test_uniquify_s3_key_keeps_subdirectories(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = await sandbox._uniquify_s3_key(
                owner_id=owner_id, file_name="thread-42/reports/report.txt"
            )
        self.assertEqual(
            key, f"giga_agent/{owner_id}/thread-42/reports/report--ABCDEFGH.txt"
        )

    async def test_upload_file_returns_mount_path(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        fake_client = _FakeS3Client()

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_s3_key",
                AsyncMock(return_value=f"giga_agent/{owner_id}/file--ABCDEFGH.txt"),
            ),
        ):
            sandbox_path = await sandbox.upload_file(
                owner_id=owner_id,
                file_name="file.txt",
                content=b"abc",
            )

        self.assertEqual(sandbox_path, f"/bucket/giga_agent/{owner_id}/file--ABCDEFGH.txt")
        self.assertEqual(fake_client.put_calls[0]["Key"], f"giga_agent/{owner_id}/file--ABCDEFGH.txt")

    async def test_read_file_returns_redirect_for_s3(self):
        sandbox = self._sandbox()
        with (
            patch.object(
                sandbox,
                "_get_s3_object_size",
                AsyncMock(return_value=100),
            ),
            patch.object(
                sandbox,
                "_generate_presigned_url",
                AsyncMock(return_value="https://signed.example.local"),
            ) as mocked,
        ):
            result = await sandbox.read_file("/bucket/u/report.txt")

        self.assertIsInstance(result, RedirectResult)
        self.assertEqual(result.url, "https://signed.example.local")
        mocked.assert_awaited_once_with(key="u/report.txt", expires_in=3600)

    async def test_read_file_returns_content_for_html(self):
        sandbox = self._sandbox()
        with (
            patch.object(
                sandbox,
                "_get_s3_object_size",
                AsyncMock(return_value=500),
            ),
            patch.object(
                sandbox,
                "_download_s3_object",
                AsyncMock(return_value=b"<html></html>"),
            ),
        ):
            result = await sandbox.read_file("/bucket/u/page.html")

        self.assertIsInstance(result, ContentResult)
        self.assertEqual(result.data, b"<html></html>")
        self.assertEqual(result.media_type, "text/html")
        self.assertTrue(result.inline)

    async def test_read_file_returns_stream_for_large_file(self):
        sandbox = self._sandbox()
        large_size = 25 * 1024 * 1024

        mock_stream_result = StreamResult(
            stream=_empty_async_iter(),
            media_type="application/octet-stream",
            content_length=large_size,
        )
        with (
            patch.object(
                sandbox,
                "_get_s3_object_size",
                AsyncMock(return_value=large_size),
            ),
            patch.object(
                sandbox,
                "_stream_s3_object",
                AsyncMock(return_value=mock_stream_result),
            ),
        ):
            result = await sandbox.read_file("/bucket/u/big.bin")

        self.assertIsInstance(result, StreamResult)
        self.assertEqual(result.content_length, large_size)

    async def test_read_file_returns_content_for_non_s3(self):
        sandbox = self._sandbox()
        sandbox._e2b_sandbox = types.SimpleNamespace(
            files=types.SimpleNamespace(read=AsyncMock(return_value=b"payload"))
        )

        result = await sandbox.read_file("/tmp/local.txt")
        self.assertIsInstance(result, ContentResult)
        self.assertEqual(result.data, b"payload")


async def _empty_async_iter():
    return
    yield  # noqa: RET504
