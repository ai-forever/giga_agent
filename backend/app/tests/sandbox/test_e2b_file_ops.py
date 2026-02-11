import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from botocore.exceptions import ClientError

from giga_agent.sandbox.e2b import E2BSandbox


class _FakeS3Client:
    def __init__(self, existing_keys: set[str] | None = None):
        self.existing_keys = existing_keys or set()
        self.put_calls: list[dict] = []

    async def head_object(self, Bucket: str, Key: str):
        if Key in self.existing_keys:
            return {"Bucket": Bucket, "Key": Key}
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

    async def test_uniquify_s3_key_adds_counter(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        existing = {
            f"giga_agent/{owner_id}/report.txt",
            f"giga_agent/{owner_id}/report (1).txt",
        }
        fake_client = _FakeS3Client(existing_keys=existing)

        with patch("aioboto3.Session", return_value=_FakeSession(fake_client)):
            key = await sandbox._uniquify_s3_key(owner_id=owner_id, file_name="report.txt")

        self.assertEqual(key, f"giga_agent/{owner_id}/report (2).txt")

    async def test_upload_file_returns_mount_path(self):
        sandbox = self._sandbox()
        owner_id = uuid.uuid4()
        fake_client = _FakeS3Client()

        with (
            patch("aioboto3.Session", return_value=_FakeSession(fake_client)),
            patch.object(
                sandbox,
                "_uniquify_s3_key",
                AsyncMock(return_value=f"giga_agent/{owner_id}/file.txt"),
            ),
        ):
            sandbox_path = await sandbox.upload_file(
                owner_id=owner_id,
                file_name="file.txt",
                content=b"abc",
            )

        self.assertEqual(sandbox_path, f"/home/user/bucket/giga_agent/{owner_id}/file.txt")
        self.assertEqual(fake_client.put_calls[0]["Key"], f"giga_agent/{owner_id}/file.txt")

    async def test_read_file_returns_presigned_url_for_s3(self):
        sandbox = self._sandbox()
        with patch.object(
            sandbox,
            "_generate_presigned_url",
            AsyncMock(return_value="https://signed.example.local"),
        ) as mocked:
            result = await sandbox.read_file("/home/user/bucket/giga_agent/u/report.txt")

        self.assertEqual(result, "https://signed.example.local")
        mocked.assert_awaited_once_with(key="giga_agent/u/report.txt", expires_in=3600)

    async def test_read_file_returns_bytes_for_non_s3(self):
        sandbox = self._sandbox()
        sandbox._e2b_sandbox = types.SimpleNamespace(
            files=types.SimpleNamespace(read=AsyncMock(return_value=b"payload"))
        )

        result = await sandbox.read_file("/tmp/local.txt")
        self.assertEqual(result, b"payload")
