"""S3 file upload / read / delete for E2B sandboxes."""

import contextlib
import mimetypes
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import PurePosixPath

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    RedirectResult,
    StreamResult,
)
from giga_agent.sandbox.e2b.constants import (
    S3_MOUNT_PREFIX,
    _S3_KEY_PREFIX,
    _S3_SUFFIX_ALPHABET,
)

logger = get_logger(__name__)


class S3FilesMixin:
    """Mixin providing S3-backed file upload/read/delete for E2B sandboxes.

    Expects the host class to expose:
      - ``s3_endpoint``, ``s3_region``, ``s3_bucket`` (str)
      - ``aws_access_key_id``, ``aws_secret_access_key`` (str)
      - ``owner_id`` (uuid.UUID | None)
      - ``_s3_prefix_ready`` (bool)
      - ``_e2b_sandbox`` (E2B AsyncSandbox or None)
      - ``_ensure_e2b_sandbox_connected()``
    """

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        """Upload a file to the user's S3 prefix with unique naming.

        Returns sandbox_path like ``/bucket/{relative_path}``.
        """
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        clean_name = file_name.strip()
        if not clean_name:
            raise ValueError("file_name must not be empty")

        await self._ensure_user_prefix_exists(owner_id=owner_id)
        rel_path = self._uniquify_relative_s3_path(file_name=clean_name)
        key = self._s3_key_for_relative_path(rel_path, owner_id=owner_id)

        content_type, _ = mimetypes.guess_type(clean_name)
        if not content_type:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") and "charset" not in content_type:
            content_type += "; charset=utf-8"

        session = aioboto3.Session()
        last_error: Exception | None = None
        for _ in range(10):
            try:
                async with session.client(
                    "s3",
                    endpoint_url=self.s3_endpoint,
                    region_name=self.s3_region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                ) as s3:
                    await s3.put_object(
                        Bucket=self.s3_bucket,
                        Key=key,
                        Body=content,
                        ContentType=content_type,
                        IfNoneMatch="*",
                    )
                    return f"{S3_MOUNT_PREFIX}{rel_path}"
            except ClientError as e:
                code = (e.response.get("Error") or {}).get("Code")
                if code in {"PreconditionFailed", "412"}:
                    rel_path = self._uniquify_relative_s3_path(file_name=clean_name)
                    key = self._s3_key_for_relative_path(rel_path, owner_id=owner_id)
                    last_error = e
                    continue
                raise RuntimeError(f"S3 upload failed: {e}") from e
            except BotoCoreError as e:
                raise RuntimeError(f"S3 upload failed: {e}") from e

        raise RuntimeError(
            "Failed to upload file after retries due to concurrent name collisions"
        ) from last_error

    def requires_running_for_upload(self) -> bool:
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        if self._is_s3_path(sandbox_path):
            key = self._s3_key_from_sandbox_path(sandbox_path)
            content_type, _ = mimetypes.guess_type(sandbox_path)
            media_type = content_type or "application/octet-stream"
            inline = sandbox_path.lower().endswith((".html", ".htm"))

            size = await self._get_s3_object_size(key)
            if size >= LARGE_FILE_THRESHOLD:
                return await self._stream_s3_object(
                    key,
                    media_type=media_type,
                    inline=inline,
                    content_length=size,
                )
            if inline:
                data = await self._download_s3_object(key)
                return ContentResult(data=data, media_type=media_type, inline=True)
            url = await self._generate_presigned_url(key=key, expires_in=3600)
            return RedirectResult(url=url)

        # non-persisted путь внутри песочницы -> через SandboxAPI (стриминг)
        return await self._api_read_file(sandbox_path)

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        return not self._is_s3_path(sandbox_path)

    async def delete_file(self, sandbox_path: str) -> None:
        if self._is_s3_path(sandbox_path):
            key = self._s3_key_from_sandbox_path(sandbox_path)
            await self._delete_s3_object(key)
            return

        await self._api_delete_file(sandbox_path)

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        return not self._is_s3_path(sandbox_path)

    async def write_file_content(self, sandbox_path: str, content: bytes) -> None:
        if self._is_s3_path(sandbox_path):
            key = self._s3_key_from_sandbox_path(sandbox_path)
            await self._put_s3_object(key, content)
            return

        await self._api_write_file(sandbox_path, content)

    async def file_exists(self, sandbox_path: str) -> bool:
        if self._is_s3_path(sandbox_path):
            key = self._s3_key_from_sandbox_path(sandbox_path)
            return await self._s3_object_exists(key)

        return await self._api_file_exists(sandbox_path)

    def requires_running_for_write(self, sandbox_path: str) -> bool:
        return not self._is_s3_path(sandbox_path)

    def requires_running_for_file_exists(self, sandbox_path: str) -> bool:
        return not self._is_s3_path(sandbox_path)

    # ------------------------------------------------------------------
    # S3 helpers
    # ------------------------------------------------------------------

    def _is_s3_path(self, path: str) -> bool:
        return path.startswith(S3_MOUNT_PREFIX)

    def _s3_key_from_sandbox_path(self, path: str) -> str:
        rel_path = self._relative_path_from_sandbox_path(path)
        return self._s3_key_for_relative_path(rel_path)

    async def _get_s3_object_size(self, key: str) -> int:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                resp = await s3.head_object(Bucket=self.s3_bucket, Key=key)
                return int(resp["ContentLength"])
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to get S3 object size for '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to get S3 object size for '{key}': {e}") from e

    async def _download_s3_object(self, key: str) -> bytes:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                resp = await s3.get_object(Bucket=self.s3_bucket, Key=key)
                return await resp["Body"].read()
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to download S3 object '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to download S3 object '{key}': {e}") from e

    async def _put_s3_object(self, key: str, content: bytes) -> None:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        content_type = "application/octet-stream"
        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                await s3.put_object(
                    Bucket=self.s3_bucket,
                    Key=key,
                    Body=content,
                    ContentType=content_type,
                )
        except ClientError as e:
            raise RuntimeError(f"S3 write failed: {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"S3 write failed: {e}") from e

    async def _s3_object_exists(self, key: str) -> bool:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                await s3.head_object(Bucket=self.s3_bucket, Key=key)
                return True
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return False
            raise RuntimeError(f"S3 head_object failed: {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"S3 head_object failed: {e}") from e

    async def _delete_s3_object(self, key: str) -> None:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                await s3.delete_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return
            raise RuntimeError(f"Failed to delete S3 object '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to delete S3 object '{key}': {e}") from e

    async def _stream_s3_object(
        self,
        key: str,
        *,
        media_type: str = "application/octet-stream",
        inline: bool = False,
        content_length: int | None = None,
    ) -> StreamResult:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        stack = contextlib.AsyncExitStack()
        try:
            s3 = await stack.enter_async_context(
                session.client(
                    "s3",
                    endpoint_url=self.s3_endpoint,
                    region_name=self.s3_region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
            )
            resp = await s3.get_object(Bucket=self.s3_bucket, Key=key)
        except ClientError as e:
            with contextlib.suppress(Exception):
                await stack.aclose()
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to stream S3 object '{key}': {e}") from e
        except BotoCoreError as e:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise RuntimeError(f"Failed to stream S3 object '{key}': {e}") from e
        except Exception:
            with contextlib.suppress(Exception):
                await stack.aclose()
            raise

        async def _chunk_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp["Body"]:
                    yield chunk
            finally:
                with contextlib.suppress(Exception):
                    await stack.aclose()

        return StreamResult(
            stream=_chunk_iter(),
            media_type=media_type,
            inline=inline,
            content_length=content_length,
        )

    async def _generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                await s3.head_object(Bucket=self.s3_bucket, Key=key)
                return await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.s3_bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise RuntimeError(f"Failed to generate S3 URL for '{key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to generate S3 URL for '{key}': {e}") from e

    # ------------------------------------------------------------------
    # S3 path / prefix helpers
    # ------------------------------------------------------------------

    def _validate_relative_file_name(self, file_name: str) -> PurePosixPath:
        clean = file_name.strip().replace("\\", "/").lstrip("/")
        path = PurePosixPath(clean)
        if path.name in {"", ".", ".."}:
            raise ValueError("file_name must contain a valid file name")
        if any(part in {".", ".."} for part in path.parts):
            raise ValueError("file_name must not contain '.' or '..' path segments")
        return path

    def _uniquify_relative_s3_path(self, file_name: str) -> str:
        path = self._validate_relative_file_name(file_name)
        suffix_id = self._random_key_suffix()
        plotly_json_suffix = ".plotly.json"
        name = path.name
        if name.lower().endswith(plotly_json_suffix) and len(name) > len(
            plotly_json_suffix
        ):
            suffix_start = len(name) - len(plotly_json_suffix)
            stem = name[:suffix_start]
            suffix = name[suffix_start:]
        else:
            stem = path.stem or path.name
            suffix = path.suffix
        candidate_name = (
            f"{stem}--{suffix_id}{suffix}" if suffix else f"{stem}--{suffix_id}"
        )

        parent = path.parent
        parent_parts = (
            []
            if str(parent) in {"", "."}
            else [p for p in parent.parts if p not in {"", "."}]
        )

        rel_path = (
            PurePosixPath(*parent_parts, candidate_name)
            if parent_parts
            else PurePosixPath(candidate_name)
        )
        return rel_path.as_posix()

    def _relative_path_from_sandbox_path(self, path: str) -> str:
        if not self._is_s3_path(path):
            raise ValueError(f"Path '{path}' is not under S3 mount '{S3_MOUNT_PREFIX}'")

        rel_path = path[len(S3_MOUNT_PREFIX) :].strip("/")
        if not rel_path:
            raise ValueError(f"Path '{path}' does not contain a valid relative path")

        validated = self._validate_relative_file_name(rel_path)
        return validated.as_posix()

    def _s3_key_for_relative_path(
        self,
        rel_path: str,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> str:
        validated = self._validate_relative_file_name(rel_path)
        return f"{self._user_s3_prefix(owner_id)}/{validated.as_posix()}"

    def _user_s3_prefix(self, owner_id: uuid.UUID | None = None) -> str:
        resolved_owner_id = owner_id or self._require_owner_id()
        return f"{_S3_KEY_PREFIX}/{resolved_owner_id}"

    def _user_s3_marker_key(self, owner_id: uuid.UUID | None = None) -> str:
        return f"{self._user_s3_prefix(owner_id)}/"

    def _require_owner_id(self) -> uuid.UUID:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required for E2B S3 user root")
        return self.owner_id

    async def _ensure_user_prefix_exists(
        self,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        import aioboto3
        from botocore.exceptions import BotoCoreError, ClientError

        resolved_owner_id = owner_id or self._require_owner_id()
        if self._s3_prefix_ready and resolved_owner_id == self.owner_id:
            return

        marker_key = self._user_s3_marker_key(resolved_owner_id)
        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ) as s3:
                try:
                    await s3.head_object(Bucket=self.s3_bucket, Key=marker_key)
                except ClientError as e:
                    code = (e.response.get("Error") or {}).get("Code")
                    if code not in {"NoSuchKey", "404"}:
                        raise
                    await s3.put_object(
                        Bucket=self.s3_bucket,
                        Key=marker_key,
                        Body=b"",
                    )
        except ClientError as e:
            raise RuntimeError(f"Failed to ensure S3 prefix '{marker_key}': {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to ensure S3 prefix '{marker_key}': {e}") from e

        if resolved_owner_id == self.owner_id:
            self._s3_prefix_ready = True

    def _random_key_suffix(self) -> str:
        return "".join(secrets.choice(_S3_SUFFIX_ALPHABET) for _ in range(8))
