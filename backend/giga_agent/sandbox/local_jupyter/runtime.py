from __future__ import annotations

import asyncio
import mimetypes
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any

import aiofiles
import aiofiles.os
from pydantic import Field, PrivateAttr

from giga_agent.conf import get_settings
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    StreamResult,
)
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.local_jupyter.dependencies import ensure_jupyter_dependencies
from giga_agent.sandbox.local_jupyter.manager import (
    LOCAL_JUPYTER_KERNEL_NAME,
    get_local_jupyter_server_manager,
)
from giga_agent.sandbox.manager.types import SetSandboxStatusAction
from giga_agent.sandbox.registry import SandboxRegistry

BUCKET_PREFIX = "/bucket/"
_LOCAL_FILE_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@SandboxRegistry.register("local_jupyter")
class LocalJupyterSandbox(JupyterSandbox):
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Sandbox owner id injected by runtime factory",
    )
    external_id: str | None = Field(
        default=None,
        description="Managed Jupyter process pid",
    )
    jupyter_token: str | None = Field(
        default=None,
        description="Managed Jupyter auth token",
    )
    runtime_dir: str | None = Field(
        default=None,
        description="Managed Jupyter runtime directory",
    )
    base_url: str = Field(
        default="",
        description="Base URL of the managed local Jupyter server",
    )

    _runtime_fields = JupyterSandbox._runtime_fields | {
        "owner_id",
        "jupyter_token",
        "runtime_dir",
    }
    _sandbox_root_dir: Path = PrivateAttr(default_factory=Path)

    def model_post_init(self, __context: Any) -> None:
        if self.jupyter_token:
            self._token = self.jupyter_token

        root_dir_raw = get_settings().giga_agent_local_jupyter_files_path
        if root_dir_raw:
            self._sandbox_root_dir = Path(root_dir_raw).expanduser().resolve()
        else:
            self._sandbox_root_dir = (
                ensure_giga_agent_dir() / "local_jupyter" / "files"
            ).resolve()

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        validated = await super().validate_settings(settings)
        ensure_jupyter_dependencies()

        return validated

    def get_connection_settings(self) -> dict:
        settings: dict[str, Any] = {
            "external_id": self.external_id,
            "jupyter_token": self._token or self.jupyter_token,
            "runtime_dir": self.runtime_dir,
            "base_url": self.base_url or None,
        }
        return {key: value for key, value in settings.items() if value is not None}

    def _get_kernel_request_payload(self) -> dict[str, Any] | None:
        return {"name": LOCAL_JUPYTER_KERNEL_NAME}

    async def up(self) -> None:
        ensure_jupyter_dependencies()
        handle = await get_local_jupyter_server_manager().ensure_started()
        self.base_url = handle.base_url
        self.runtime_dir = handle.runtime_dir
        self._token = handle.token
        self.jupyter_token = handle.token
        self.external_id = str(handle.pid)

    async def stop(self) -> None:
        return None

    async def is_up(self) -> bool:
        if not self.base_url or not self._token:
            handle = await get_local_jupyter_server_manager().get_active_handle()
            if handle is None:
                return False
            self.base_url = handle.base_url
            self.runtime_dir = handle.runtime_dir
            self._token = handle.token
            self.jupyter_token = handle.token
            self.external_id = str(handle.pid)
        return await super().is_up()

    @classmethod
    async def cleanup_orphans(
        cls,
        *,
        providers: list[Any],
        sandboxes: list[Any],
    ) -> list[SetSandboxStatusAction]:
        del providers
        handle = await get_local_jupyter_server_manager().get_active_handle()
        if handle is not None:
            return []

        actions: list[SetSandboxStatusAction] = []
        for sandbox in sandboxes:
            if sandbox.status not in (
                SandboxStatus.RUNNING,
                SandboxStatus.STARTING,
                SandboxStatus.STOPPING,
            ):
                continue
            actions.append(
                SetSandboxStatusAction(
                    provider_type="local_jupyter",
                    provider_id=sandbox.provider_id,
                    sandbox_id=sandbox.id,
                    status=SandboxStatus.STOPPED,
                    reason="managed_local_jupyter_server_missing",
                    clear_runtime_connection=True,
                )
            )
        return actions

    @classmethod
    async def stop_external_runtime(cls, external_id: str) -> None:
        try:
            pid = int(external_id)
        except ValueError:
            return
        await get_local_jupyter_server_manager().stop_pid(pid)

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
        async with aiofiles.open(target, "wb") as file_obj:
            await file_obj.write(content)
        return str(target.resolve())

    def requires_running_for_upload(self) -> bool:
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        local_path = self._resolve_readable_path(sandbox_path)
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

        async with aiofiles.open(local_path, "rb") as file_obj:
            data = await file_obj.read()

        return ContentResult(data=data, media_type=media_type, inline=inline)

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        return False

    async def delete_file(self, sandbox_path: str) -> None:
        local_path = self._resolve_readable_path(sandbox_path)
        try:
            await aiofiles.os.remove(local_path)
        except FileNotFoundError:
            pass

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        return False

    async def _stream_local_file(
        self,
        path: Path,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        async with aiofiles.open(path, "rb") as file_obj:
            while True:
                chunk = await file_obj.read(chunk_size)
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
            else [part for part in parent.parts if part not in {"", "."}]
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
        if not sandbox_path.startswith(BUCKET_PREFIX):
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        key = sandbox_path[len(BUCKET_PREFIX) :].strip("/")
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

    def _resolve_readable_path(self, sandbox_path: str) -> Path:
        if sandbox_path.startswith(BUCKET_PREFIX):
            return self._local_path_from_bucket_path(sandbox_path)
        return Path(sandbox_path).expanduser().resolve()
