from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import uuid
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from giga_agent.conf import get_settings
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory
from giga_agent.utils.langgraph_sdk import get_client

if TYPE_CHECKING:
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from giga_agent.models.file import FileType
    from giga_agent.sandbox.manager import UploadFileSpec


def _get_schema_builder_cls():
    from genson import SchemaBuilder

    return SchemaBuilder


def _get_file_upload_helpers():
    from giga_agent.models.file import FileResponse
    from giga_agent.sandbox.manager import SandboxManager

    return FileResponse, SandboxManager


def _get_max_tool_size() -> int:
    raw = str(get_settings().giga_agent_tool_max_size)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 25000


def _resolve_thread_id(config: RunnableConfig | dict[str, Any]) -> str:
    metadata = config.get("metadata", {}) if isinstance(config, dict) else {}
    thread_id = metadata.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    return f"temporary/{uuid.uuid4().hex}"


def _resolve_owner_id(config: RunnableConfig | dict[str, Any]) -> uuid.UUID | None:
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    user = configurable.get("langgraph_auth_user", {})
    identity = user.get("identity")
    if identity is None:
        return None
    if isinstance(identity, uuid.UUID):
        return identity
    if isinstance(identity, str):
        try:
            return uuid.UUID(identity)
        except ValueError:
            return None
    return None


def _normalize_result_payload(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


def _safe_json_dumps(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(data, ensure_ascii=False, default=str)


async def _upload_files_for_owner(
    owner_id: uuid.UUID,
    files: list[UploadFileSpec],
) -> list[dict[str, Any]]:
    if not files:
        return []

    factory = await get_session_factory()
    async with factory() as session:
        FileResponse, SandboxManager = _get_file_upload_helpers()
        manager = SandboxManager(session)
        uploaded = await manager.upload_files_for_user(user_id=owner_id, files=files)

    return [
        FileResponse.model_validate(item).model_dump(mode="json")
        for item in uploaded.files
    ]


async def _save_tool_result(
    result_payload: Any,
    action: dict[str, Any],
    config: RunnableConfig | dict[str, Any],
) -> str | None:
    owner_id = _resolve_owner_id(config)
    if owner_id is None:
        return None

    thread_id = _resolve_thread_id(config)
    call_id = action.get("id") or uuid.uuid4().hex
    file_name = f"{thread_id}/functions/{call_id}.json"

    content = _safe_json_dumps(result_payload).encode("utf-8")
    try:
        uploaded = await _upload_files_for_owner(
            owner_id=owner_id,
            files=[
                {
                    "file_name": file_name,
                    "content": content,
                    "file_type": "text",
                }
            ],
        )
    except Exception:
        return file_name
    if uploaded:
        return uploaded[0].get("sandbox_path")
    return file_name


def _build_attachment_info(file_type: str, path: str) -> str:
    if file_type == "audio":
        title = "В результате выполнения был сгенерирован аудиофайл. "
        hint = f'"[аудио](attachment:{path})" '
    elif file_type == "video":
        title = "В результате выполнения был сгенерирован видеофайл. "
        hint = f'"[видео](attachment:{path})" '
    else:
        title = "В результате выполнения было сгенерировано изображение. "
        hint = f'"![alt-текст](attachment:{path})" '

    return (
        f"{title}Путь до него '{path}'. "
        f"Ты можешь показать это пользователю с помощью через {hint}"
    )


def _should_compress(tool: Optional[BaseTool], result_size: int, max_size: int) -> bool:
    if tool is None:
        return result_size > max_size

    extras = getattr(tool, "extras", {}) or {}
    if extras.get("not_compress") is True:
        return False
    return result_size > max_size


_MIME_EXTENSION_MAP = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _should_skip_process(tool: Optional[BaseTool]) -> bool:
    if tool is None:
        return False
    extras = getattr(tool, "extras", {}) or {}
    return bool(extras.get("not_process"))


# Инструменты, чей результат никогда не оборачивается в result_path-файл.
# Иначе возникает цикл: LLM читает файл через python → stdout снова > лимита →
# middleware сохраняет новый файл → LLM получает новый путь → читает → цикл.
_INLINE_OUTPUT_TOOLS = {"python", "shell"}


def _truncate_utf8(text: str, max_size: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_size:
        return text
    truncated = encoded[:max_size].decode("utf-8", errors="ignore")
    hint = (
        f"\n\n[... вывод обрезан до {max_size} байт. "
        "Исходный вывод был слишком большим для контекста. "
        "Перепиши код: используй срезы/фильтрацию/агрегацию, "
        "либо сохрани результат в файл и читай его по частям.]"
    )
    return truncated + hint


def _build_inline_output_message(
    normalized_result: Any,
    action: dict[str, Any],
    tool_attachments: list[dict[str, Any]],
    message: str,
    max_size: int,
) -> ToolMessage:
    if isinstance(normalized_result, dict) and isinstance(
        normalized_result.get("output"), str
    ):
        output_text = normalized_result["output"]
        truncated = _truncate_utf8(output_text, max_size)
        if truncated is not output_text:
            normalized_result = {**normalized_result, "output": truncated}
    else:
        serialized = _safe_json_dumps(normalized_result)
        if len(serialized.encode("utf-8")) > max_size:
            normalized_result = {
                "output": _truncate_utf8(serialized, max_size),
            }

    payload: dict[str, Any] = {"data": normalized_result}
    if message:
        payload["message"] = message

    return ToolMessage(
        tool_call_id=action.get("id"),
        content=_safe_json_dumps(payload),
        additional_kwargs={
            "tool_attachments": tool_attachments,
            "tool_name": action.get("name"),
        },
    )


async def process_tool_result(
    result: Any,
    action: dict[str, Any],
    tool_attachments: list[dict[str, Any]],
    config: RunnableConfig | dict[str, Any],
    tool: Optional[BaseTool] = None,
    message: str = "",
) -> ToolMessage:
    normalized_result = _normalize_result_payload(result)
    tool_name = action.get("name")
    if tool_name == "think" and normalized_result in ("", None):
        normalized_result = ""

    if action.get("name") in ["message", "think"] or _should_skip_process(tool):
        return ToolMessage(
            tool_call_id=action.get("id"),
            content=_safe_json_dumps(normalized_result),
            additional_kwargs={
                "tool_attachments": tool_attachments,
                "tool_name": tool_name,
                "tool_args": action.get("args"),
            },
        )

    result_path = await _save_tool_result(
        normalized_result, action=action, config=config
    )
    saved_result_message = (
        "Результат вызова инструмента сохранен в файле JSON по пути "
        f"'{result_path}'. "
    )

    serialized = _safe_json_dumps(normalized_result)
    compress = _should_compress(
        tool=tool, result_size=len(serialized), max_size=_get_max_tool_size()
    )

    payload: dict[str, Any]
    if compress:
        schema = _get_schema_builder_cls()()
        schema.add_object(obj=normalized_result)
        extra_msg = (
            "Результат функции вышел слишком длинным. "
            "Используй result_path и python для детального анализа."
        )
        full_message = "\n".join(
            part for part in [message, saved_result_message, extra_msg] if part
        )
        payload = {
            "message": full_message,
            "schema": schema.to_schema(),
            "result_path": result_path,
        }
    else:
        payload = {
            "data": normalized_result,
            "result_path": result_path,
        }
        payload["message"] = "\n".join(
            part for part in [message, saved_result_message] if part
        )

    return ToolMessage(
        tool_call_id=action.get("id"),
        content=_safe_json_dumps(payload),
        additional_kwargs={
            "tool_attachments": tool_attachments,
            "tool_name": tool_name,
            "tool_args": action.get("args"),
        },
    )


def _normalize_mcp_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    if isinstance(content, dict):
        nested = content.get("content")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if "type" in content:
            return [content]
    return []


def _decode_base64_payload(raw: Any) -> bytes | None:
    if not isinstance(raw, str):
        return None
    try:
        return base64.b64decode(raw)
    except (binascii.Error, ValueError):
        return None


def _resolve_mcp_file_meta(content_type: str, mime_type: str) -> tuple[FileType, str]:
    ext = _MIME_EXTENSION_MAP.get(mime_type)
    if not ext:
        guessed = mimetypes.guess_extension(mime_type)
        ext = guessed if guessed else ".bin"

    if content_type == "audio":
        return "audio", ext
    if content_type == "video":
        return "video", ext
    if content_type == "image":
        return "image", ext
    return "other", ext


async def process_mcp_content(
    content: Any,
    config: RunnableConfig | dict[str, Any],
) -> tuple[Any, list[dict[str, Any]], str]:
    owner_id = _resolve_owner_id(config)
    thread_id = _resolve_thread_id(config)

    upload_specs: list[UploadFileSpec] = []
    text_parts: list[Any] = []

    for part in _normalize_mcp_parts(content):
        part_type = part.get("type")

        if part_type == "text":
            text = part.get("text")
            if isinstance(text, str):
                try:
                    text_parts.append(json.loads(text))
                except json.JSONDecodeError:
                    text_parts.append(text)
            continue

        if part_type not in {"image", "audio", "video"}:
            continue

        payload = _decode_base64_payload(part.get("data"))
        if payload is None:
            continue

        mime_type = str(part.get("mimeType", "application/octet-stream"))
        file_type, extension = _resolve_mcp_file_meta(str(part_type), mime_type)
        upload_specs.append(
            {
                "file_name": f"{thread_id}/mcp/{uuid.uuid4().hex}{extension}",
                "content": payload,
                "file_type": file_type,
            }
        )

    uploaded_files: list[dict[str, Any]] = []
    if owner_id is not None and upload_specs:
        try:
            uploaded_files = await _upload_files_for_owner(
                owner_id=owner_id,
                files=upload_specs,
            )
        except Exception:
            uploaded_files = []

    attachment_messages: list[str] = []
    for file in uploaded_files:
        path = file.get("sandbox_path") or file.get("path")
        file_type = str(file.get("file_type", "other"))
        if isinstance(path, str) and path:
            attachment_messages.append(_build_attachment_info(file_type, path))

    message = "\n".join(attachment_messages)
    if len(text_parts) == 1:
        result: Any = text_parts[0]
    elif text_parts:
        result = text_parts
    else:
        result = None

    return result, uploaded_files, message


class ToolResultMiddleware(AgentMiddleware):
    async def before_agent(
        self,
        state: AgentState,
        runtime: Runtime[Context],
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        # Sync the autonomy flag from the current run (configurable) into the
        # thread metadata so it survives resume and a page reload.
        # The frontend does not write metadata itself: on submit configurable is
        # the source of truth. On resume configurable.auto_approve is absent
        # (conf_val is None) -> no-op, the value stored in metadata is kept.
        _ = runtime, state
        configurable = config.get("configurable", {}) or {}
        conf_val = configurable.get("auto_approve")
        if conf_val is None:
            return None

        metadata = config.get("metadata", {}) or {}
        if metadata.get("auto_approve") == bool(conf_val):
            return None

        thread_id = _resolve_thread_id(config)
        if thread_id.startswith("temporary/"):
            return None

        try:
            client = get_client(config)
            await client.threads.update(
                thread_id, metadata={"auto_approve": bool(conf_val)}
            )
        except Exception:
            return None
        return None

    async def after_model(
        self,
        state: AgentState,
        runtime: Runtime[Context],
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        actions = deepcopy(state["messages"][-1].tool_calls)
        action_map = {action.get("id"): action for action in actions}
        if not actions:
            return None
        if all(action.get("name") == "think" for action in actions):
            return None

        mcp_tool_names = [tool.get("name") for tool in state.get("mcp_tools", [])]
        frontend_actions = [
            action for action in actions if action.get("name") in mcp_tool_names
        ]

        # The autonomy flag lives in thread metadata (survives resume)
        # — the frontend sends the current value.
        metadata = config.get("metadata", {}) or {}
        auto_approve = bool(metadata.get("auto_approve"))

        if frontend_actions:
            # MCP tools run on the client — an interrupt is mandatory.
            value = interrupt({"type": "tool_call", "tools": frontend_actions})
        elif auto_approve:
            # Autonomous mode without frontend_actions: don't interrupt, keep
            # executing on the server (the run finishes even with the page closed).
            return None
        else:
            value = interrupt({"type": "approve"})

        if value.get("type") == "comment":
            user_message = value.get("message")
            if user_message:
                tool_message = (
                    "Пользователь отменил вызов инструмента и оставил комментарий к твоему вызову инструмента. "
                    f'Прочитай его и реши, как действовать дальше: "{user_message}"'
                )
            else:
                tool_message = (
                    "Пользователь отменил вызов инструмента без комментария. "
                    "Не выполняй этот вызов. Спроси пользователя, чем можешь помочь."
                )
            tools_response = [
                ToolMessage(
                    tool_call_id=action.get("id", str(uuid.uuid4())),
                    content=tool_message,
                    additional_kwargs={"tool_name": action.get("name")},
                ) for action in actions
            ]
            return {"messages": tools_response}

        if not frontend_actions:
            return None

        tool_responses: list[ToolMessage] = []
        for result in value.get("results", []):
            action_id = result.get("id")
            action = action_map.get(action_id)
            if action is None:
                continue

            mcp_content = result.get("result", {}).get("content")
            data, tool_attachments, message = await process_mcp_content(
                mcp_content,
                config,
            )
            tool_responses.append(
                await process_tool_result(
                    data,
                    action,
                    tool_attachments,
                    config,
                    None,
                    message,
                )
            )

        if tool_responses:
            return {"messages": tool_responses}
        return None

    async def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        if isinstance(result, ToolMessage):
            attachments = (result.additional_kwargs or {}).get("tool_attachments", [])
            return await process_tool_result(
                result.content,
                request.tool_call,
                attachments,
                request.runtime.config,
                request.tool,
            )
        return result
