from __future__ import annotations

import json
import uuid
from typing import Any, TypedDict
from urllib.parse import urlencode

from giga_agent.conf import GIGA_PREFIX_API, get_settings
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage

from giga_agent.core.db import get_session_factory
from giga_agent.models.file import FileResponse, FileType
from giga_agent.modules.subagents_legacy.runtime import (
    get_owner_id_from_config,
    get_owner_id_from_runtime,
)
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec


class LegacyUploadFileSpec(TypedDict):
    file_name: str
    content: bytes
    file_type: FileType


def build_file_content_by_path_api() -> str:
    settings = get_settings()
    host = (settings.giga_agent_host or "").strip().rstrip("/")
    port = (settings.giga_agent_port or "").strip()

    if host and port:
        base = f"{host}:{port}"
    elif host:
        base = host
    else:
        base = ""

    if base:
        return f"{base}/api{GIGA_PREFIX_API}/files/content/by-path"
    return f"/api{GIGA_PREFIX_API}/files/content/by-path"


def build_file_content_by_path_url(sandbox_path: str) -> str:
    query = urlencode({"path": sandbox_path})
    return f"{build_file_content_by_path_api()}?{query}"


def resolve_upload_prefix(runtime: ToolRuntime) -> str:
    configurable = runtime.config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str):
        clean = thread_id.strip().strip("/")
        if clean:
            return clean
    return f"temporary/{uuid.uuid4().hex}"


async def upload_files_for_runtime_user(
    runtime: ToolRuntime,
    files: list[LegacyUploadFileSpec],
) -> list[FileResponse]:
    owner_id = get_owner_id_from_runtime(runtime)
    return await upload_files_for_owner(owner_id=owner_id, files=files)


async def upload_files_for_config_user(
    config: dict,
    files: list[LegacyUploadFileSpec],
) -> list[FileResponse]:
    owner_id = get_owner_id_from_config(config)
    return await upload_files_for_owner(owner_id=owner_id, files=files)


async def upload_files_for_owner(
    owner_id: uuid.UUID,
    files: list[LegacyUploadFileSpec],
) -> list[FileResponse]:
    upload_files: list[UploadFileSpec] = [
        {
            "file_name": f["file_name"],
            "content": f["content"],
            "file_type": f["file_type"],
        }
        for f in files
    ]

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        uploaded = await manager.upload_files_for_user(
            user_id=owner_id,
            files=upload_files,
        )

    return [FileResponse.model_validate(item) for item in uploaded.files]


def build_tool_message(
    runtime: ToolRuntime,
    *,
    tool_name: str,
    payload: dict[str, Any],
    attachments: list[FileResponse] | None = None,
) -> ToolMessage:
    tool_attachments = [item.model_dump(mode="json") for item in (attachments or [])]
    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(payload, ensure_ascii=False),
        additional_kwargs={
            "tool_name": tool_name,
            "tool_attachments": tool_attachments,
        },
    )
