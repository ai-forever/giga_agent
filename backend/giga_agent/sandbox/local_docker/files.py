"""File upload / read / delete for Docker sandboxes with local bucket storage."""

import asyncio
import mimetypes
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath

import aiofiles
import aiofiles.os

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    StreamResult,
)
from giga_agent.sandbox.local_docker.constants import (
    BUCKET_PREFIX,
    _LOCAL_FILE_SUFFIX_ALPHABET,
)

logger = get_logger(__name__)


class FilesMixin:
    """Mixin providing file upload/read/delete for Docker sandboxes.

    Expects the host class to expose:
      - ``owner_id`` (uuid.UUID | None)
      - ``_sandbox_root_dir`` (Path)
      - ``_container`` (docker Container or None)
      - ``_ensure_container_connected()``
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
        rel_path = self._uniquify_bucket_rel_path(owner_id=owner_id, file_name=file_name)
        target = self._user_root_dir(owner_id) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as f:
            await f.write(content)
        return f"{BUCKET_PREFIX}{rel_path.as_posix()}"

    def requires_running_for_upload(self) -> bool:
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        if self._is_bucket_path(sandbox_path):
            local_path = self._local_path_from_bucket_path(sandbox_path)
            if not local_path.exists() or not local_path.is_file():
                raise FileNotFoundError(f"File not found: {sandbox_path}")

            media_type, _ = mimetypes.guess_type(local_path.name)
            if not media_type:
                media_type = "application/octet-stream"
            inline = local_path.suffix.lower() in {".html", ".htm"}

            size = local_path.stat().st_size
            if size >= LARGE_FILE_THRESHOLD:
                return StreamResult(
                    stream=self._stream_local_file(local_path),
                    media_type=media_type,
                    inline=inline,
                    content_length=size,
                )

            async with aiofiles.open(local_path, "rb") as f:
                data = await f.read()

            return ContentResult(data=data, media_type=media_type, inline=inline)

        await self._ensure_container_connected()
        assert self._container is not None
        exit_code, output = self._container.exec_run(
            cmd=["cat", "--", sandbox_path],
            stdout=True,
            stderr=True,
        )
        if exit_code != 0:
            stderr = output.decode(errors="ignore")
            if "No such file or directory" in stderr:
                raise FileNotFoundError(f"File not found: {sandbox_path}")
            raise RuntimeError(
                f"Failed to read file '{sandbox_path}': {stderr}".strip()
            )

        media_type, _ = mimetypes.guess_type(sandbox_path)
        return ContentResult(
            data=bytes(output), media_type=media_type or "application/octet-stream"
        )

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        return not self._is_bucket_path(sandbox_path)

    async def delete_file(self, sandbox_path: str) -> None:
        if self._is_bucket_path(sandbox_path):
            local_path = self._local_path_from_bucket_path(sandbox_path)
            try:
                await aiofiles.os.remove(local_path)
            except FileNotFoundError:
                pass
            return

        await self._ensure_container_connected()
        assert self._container is not None
        exit_code, output = self._container.exec_run(
            cmd=["rm", "-f", "--", sandbox_path],
            stdout=True,
            stderr=True,
        )
        if exit_code != 0:
            stderr = output.decode(errors="ignore")
            raise RuntimeError(
                f"Failed to delete file '{sandbox_path}': {stderr}".strip()
            )

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        return not self._is_bucket_path(sandbox_path)

    # ------------------------------------------------------------------
    # bucket / local path helpers
    # ------------------------------------------------------------------

    def _is_bucket_path(self, path: str) -> bool:
        return path.startswith(BUCKET_PREFIX)

    async def _stream_local_file(
        self, path: Path, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0)

    def _validate_relative_file_name(self, file_name: str) -> PurePosixPath:
        clean = file_name.strip().replace("\\", "/").lstrip("/")
        path = PurePosixPath(clean)
        if path.name in {"", ".", ".."}:
            raise ValueError("file_name must contain a valid file name")
        if any(part in {".", ".."} for part in path.parts):
            raise ValueError("file_name must not contain '.' or '..' path segments")
        return path

    def _uniquify_bucket_rel_path(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
    ) -> PurePosixPath:
        path = self._validate_relative_file_name(file_name)
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

        parent = path.parent
        parent_parts = (
            []
            if str(parent) in {"", "."}
            else [p for p in parent.parts if p not in {"", "."}]
        )
        user_root = self._user_root_dir(owner_id)
        for _ in range(10):
            suffix_id = self._random_key_suffix()
            candidate_name = (
                f"{stem}--{suffix_id}{suffix}" if suffix else f"{stem}--{suffix_id}"
            )
            rel_path = (
                PurePosixPath(*parent_parts, candidate_name)
                if parent_parts
                else PurePosixPath(candidate_name)
            )
            target = user_root / Path(*rel_path.parts)
            if not target.exists():
                return rel_path

        raise RuntimeError(
            "Failed to generate unique local upload file name after retries"
        )

    def _random_key_suffix(self) -> str:
        return "".join(secrets.choice(_LOCAL_FILE_SUFFIX_ALPHABET) for _ in range(8))

    def _user_root_dir(self, owner_id: uuid.UUID) -> Path:
        root = self._sandbox_root_dir
        root.mkdir(parents=True, exist_ok=True)
        user_root = (root / str(owner_id)).resolve()
        user_root.mkdir(parents=True, exist_ok=True)
        return user_root

    def _local_path_from_bucket_path(self, sandbox_path: str) -> Path:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required to resolve sandbox path")
        key = sandbox_path[len(BUCKET_PREFIX):].strip("/")
        if not key:
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        rel = PurePosixPath(key)
        if any(part in {".", ".."} for part in rel.parts):
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        user_root = self._user_root_dir(self.owner_id).resolve()
        local_path = (user_root / Path(*rel.parts)).resolve()
        if user_root != local_path and user_root not in local_path.parents:
            raise ValueError(f"Path escapes user sandbox root: {sandbox_path}")
        return local_path
