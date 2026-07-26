import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from botocore.exceptions import ClientError

from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
from giga_agent.sandbox.e2b import E2BSandbox


class _FakeS3Client:
    def __init__(
        self, existing_keys: set[str] | None = None, content_length: int = 100
    ):
        self.existing_keys = existing_keys or set()
        self.put_calls: list[dict] = []
        self.upload_calls: list[dict] = []
        self._content_length = content_length

    async def head_object(self, Bucket: str, Key: str):
        if Key in self.existing_keys:
            return {"Bucket": Bucket, "Key": Key, "ContentLength": self._content_length}
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    async def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ETag": "etag"}

    async def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None):
        self.upload_calls.append(
            {
                "Bucket": Bucket,
                "Key": Key,
                "ExtraArgs": ExtraArgs,
                "data": Fileobj.read(),
            }
        )
        self.existing_keys.add(Key)
        return None

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
            owner_id=uuid.uuid4(),
        )

    async def test_uniquify_relative_s3_path_adds_random_suffix(self):
        sandbox = self._sandbox()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = sandbox._uniquify_relative_s3_path(file_name="report.txt")

        self.assertEqual(key, "report--ABCDEFGH.txt")

    async def test_uniquify_relative_s3_path_adds_suffix_before_plotly_json_extension(
        self,
    ):
        sandbox = self._sandbox()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = sandbox._uniquify_relative_s3_path(file_name="chart.plotly.json")

        self.assertEqual(key, "chart--ABCDEFGH.plotly.json")

    async def test_uniquify_relative_s3_path_keeps_subdirectories(self):
        sandbox = self._sandbox()
        with patch.object(sandbox, "_random_key_suffix", return_value="ABCDEFGH"):
            key = sandbox._uniquify_relative_s3_path(
                file_name="thread-42/reports/report.txt"
            )
        self.assertEqual(key, "thread-42/reports/report--ABCDEFGH.txt")

    async def test_s3_key_for_relative_path_adds_user_prefix(self):
        sandbox = self._sandbox()
        key = sandbox._s3_key_for_relative_path("thread-42/reports/report.txt")
        self.assertEqual(
            key,
            f"giga_agent/{sandbox.owner_id}/thread-42/reports/report.txt",
        )

    async def test_ensure_user_prefix_exists_creates_marker_object_when_missing(self):
        sandbox = self._sandbox()
        fake_client = _FakeS3Client()

        with patch("aioboto3.Session", return_value=_FakeSession(fake_client)):
            await sandbox._ensure_user_prefix_exists()

        self.assertEqual(
            fake_client.put_calls,
            [
                {
                    "Bucket": "bucket",
                    "Key": f"giga_agent/{sandbox.owner_id}/",
                    "Body": b"",
                }
            ],
        )

    async def test_upload_file_returns_mount_path(self):
        sandbox = self._sandbox()
        fake_client = _FakeS3Client()

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_relative_s3_path",
                return_value="file--ABCDEFGH.txt",
            ),
        ):
            sandbox_path = await sandbox.upload_file(
                owner_id=sandbox.owner_id,
                file_name="file.txt",
                content=b"abc",
            )

        self.assertEqual(sandbox_path, "/bucket/file--ABCDEFGH.txt")
        self.assertEqual(
            fake_client.put_calls[0]["Key"], f"giga_agent/{sandbox.owner_id}/"
        )
        self.assertEqual(
            fake_client.put_calls[1]["Key"],
            f"giga_agent/{sandbox.owner_id}/file--ABCDEFGH.txt",
        )

    async def test_upload_file_keeps_nested_paths_under_user_prefix(self):
        sandbox = self._sandbox()
        fake_client = _FakeS3Client()

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_relative_s3_path",
                return_value="thread-42/reports/report--ABCDEFGH.txt",
            ),
        ):
            sandbox_path = await sandbox.upload_file(
                owner_id=sandbox.owner_id,
                file_name="thread-42/reports/report.txt",
                content=b"abc",
            )

        self.assertEqual(sandbox_path, "/bucket/thread-42/reports/report--ABCDEFGH.txt")
        self.assertEqual(
            fake_client.put_calls[1]["Key"],
            f"giga_agent/{sandbox.owner_id}/thread-42/reports/report--ABCDEFGH.txt",
        )

    async def test_upload_file_stream_uses_multipart_upload_fileobj(self):
        import io as _io

        sandbox = self._sandbox()
        fake_client = _FakeS3Client()
        fileobj = _io.BytesIO(b"streamed")

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_relative_s3_path",
                return_value="file--ABCDEFGH.txt",
            ),
        ):
            sandbox_path = await sandbox.upload_file_stream(
                owner_id=sandbox.owner_id,
                file_name="file.txt",
                fileobj=fileobj,
                size=8,
            )

        self.assertEqual(sandbox_path, "/bucket/file--ABCDEFGH.txt")
        self.assertEqual(len(fake_client.upload_calls), 1)
        call = fake_client.upload_calls[0]
        self.assertEqual(
            call["Key"], f"giga_agent/{sandbox.owner_id}/file--ABCDEFGH.txt"
        )
        self.assertEqual(call["data"], b"streamed")
        self.assertIn("charset", call["ExtraArgs"]["ContentType"])

    async def test_upload_file_stream_retries_on_key_collision(self):
        import io as _io

        sandbox = self._sandbox()
        # первый ключ уже занят -> stream должен перегенерировать имя
        taken = f"giga_agent/{sandbox.owner_id}/file--AAAAAAAA.txt"
        fake_client = _FakeS3Client(existing_keys={taken})
        fileobj = _io.BytesIO(b"payload")

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_relative_s3_path",
                side_effect=["file--AAAAAAAA.txt", "file--BBBBBBBB.txt"],
            ),
        ):
            sandbox_path = await sandbox.upload_file_stream(
                owner_id=sandbox.owner_id,
                file_name="file.txt",
                fileobj=fileobj,
                size=7,
            )

        self.assertEqual(sandbox_path, "/bucket/file--BBBBBBBB.txt")
        self.assertEqual(len(fake_client.upload_calls), 1)
        self.assertEqual(
            fake_client.upload_calls[0]["Key"],
            f"giga_agent/{sandbox.owner_id}/file--BBBBBBBB.txt",
        )

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
        mocked.assert_awaited_once_with(
            key=f"giga_agent/{sandbox.owner_id}/u/report.txt", expires_in=3600
        )

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
            ) as mocked_download,
        ):
            result = await sandbox.read_file("/bucket/u/page.html")

        self.assertIsInstance(result, ContentResult)
        self.assertEqual(result.data, b"<html></html>")
        self.assertEqual(result.media_type, "text/html")
        self.assertTrue(result.inline)
        mocked_download.assert_awaited_once_with(
            f"giga_agent/{sandbox.owner_id}/u/page.html"
        )

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
            ) as mocked_stream,
        ):
            result = await sandbox.read_file("/bucket/u/big.bin")

        self.assertIsInstance(result, StreamResult)
        self.assertEqual(result.content_length, large_size)
        mocked_stream.assert_awaited_once_with(
            f"giga_agent/{sandbox.owner_id}/u/big.bin",
            media_type="application/octet-stream",
            inline=False,
            content_length=large_size,
        )

    async def test_delete_file_resolves_bucket_path_with_user_prefix(self):
        sandbox = self._sandbox()
        with patch.object(sandbox, "_delete_s3_object", AsyncMock()) as mocked_delete:
            await sandbox.delete_file("/bucket/u/to-delete.txt")

        mocked_delete.assert_awaited_once_with(
            f"giga_agent/{sandbox.owner_id}/u/to-delete.txt"
        )

    async def test_read_file_non_s3_delegates_to_sandbox_api(self):
        sandbox = self._sandbox()
        with patch.object(
            sandbox,
            "_api_read_file",
            AsyncMock(return_value=ContentResult(data=b"payload")),
        ) as api_read:
            result = await sandbox.read_file("/tmp/local.txt")

        api_read.assert_awaited_once_with("/tmp/local.txt")
        self.assertIsInstance(result, ContentResult)
        self.assertEqual(result.data, b"payload")

    async def test_is_up_checks_e2b_sandbox_without_jupyter(self):
        sandbox = self._sandbox()
        sandbox.external_id = "sbx-123"
        sandbox._e2b_sandbox = types.SimpleNamespace(
            commands=types.SimpleNamespace(
                run=AsyncMock(return_value=types.SimpleNamespace(exit_code=0))
            )
        )

        self.assertTrue(await sandbox.is_up())

    async def test_is_up_returns_false_when_reconnect_fails(self):
        sandbox = self._sandbox()
        sandbox.external_id = "sbx-123"

        with patch.object(sandbox, "_reconnect", AsyncMock(return_value=None)):
            self.assertFalse(await sandbox.is_up())

    async def test_is_up_returns_false_when_probe_command_fails(self):
        sandbox = self._sandbox()
        sandbox.external_id = "sbx-123"
        sandbox._e2b_sandbox = types.SimpleNamespace(
            commands=types.SimpleNamespace(
                run=AsyncMock(side_effect=RuntimeError("boom"))
            )
        )

        self.assertFalse(await sandbox.is_up())


async def _empty_async_iter():
    return
    yield  # noqa: RET504
