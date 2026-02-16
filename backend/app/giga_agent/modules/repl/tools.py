"""Инструменты REPL модуля для выполнения Python кода в sandbox."""

from __future__ import annotations

import base64
import json
import re
import uuid
import logging
import binascii
from typing import Any

from cashews import cache
from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage

from giga_agent.core.db import get_session_factory
from giga_agent.models import UserShort, UserRepository
from giga_agent.models.file import FileResponse
from giga_agent.models.sandbox import SandboxRepository
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec

logger = logging.getLogger(__name__)

_DISPLAY_MIME_CONFIG: dict[str, tuple[str, str, str]] = {
    "application/vnd.plotly.v1+json": ("plotly_graph", ".plotly.json", "json"),
    "image/png": ("image", ".png", "base64"),
    "image/jpeg": ("image", ".jpg", "base64"),
    "image/gif": ("image", ".gif", "base64"),
    "image/svg+xml": ("image", ".svg", "text"),
    "audio/wav": ("audio", ".wav", "base64"),
    "audio/mpeg": ("audio", ".mp3", "base64"),
    "audio/ogg": ("audio", ".ogg", "base64"),
    "video/mp4": ("video", ".mp4", "base64"),
    "video/webm": ("video", ".webm", "base64"),
}


def _resolve_upload_prefix(runtime: ToolRuntime) -> str:
    configurable = runtime.config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str):
        clean = thread_id.strip().strip("/")
        if clean:
            return clean
    return f"temporary/{uuid.uuid4().hex}"


def _decode_display_payload(
    payload: Any, encoding: str, mime_type: str
) -> bytes | None:
    if encoding == "json":
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if encoding == "text":
        if isinstance(payload, str):
            return payload.encode("utf-8")
        logger.warning(
            "Unexpected text payload type for %s: %s", mime_type, type(payload)
        )
        return None
    if encoding == "base64":
        if not isinstance(payload, str):
            logger.warning(
                "Unexpected base64 payload type for %s: %s",
                mime_type,
                type(payload),
            )
            return None
        try:
            return base64.b64decode(payload)
        except (binascii.Error, ValueError):
            logger.warning("Invalid base64 payload for %s", mime_type)
            return None
    return None


def _extract_upload_specs_from_display_data(
    display_data: dict[str, Any],
    upload_prefix: str,
) -> list[UploadFileSpec]:
    files_to_upload: list[UploadFileSpec] = []
    for mime_type, payload in display_data.items():
        config = _DISPLAY_MIME_CONFIG.get(mime_type)
        if config is None:
            continue

        file_type, extension, encoding = config
        content = _decode_display_payload(
            payload, encoding=encoding, mime_type=mime_type
        )
        if content is None:
            continue

        name = f"{uuid.uuid4().hex}{extension}"
        files_to_upload.append(
            {
                "file_name": f"{upload_prefix}/{name}",
                "content": content,
                "file_type": file_type,  # type: ignore[typeddict-item]
            }
        )
    return files_to_upload


def _build_attachment_info(file_type: str, path: str) -> str:
    attachment_info = ""
    if file_type == "plotly_graph":
        attachment_info = "В результате выполнения был сгенерирован график. "
    elif file_type == "image":
        attachment_info = "В результате выполнения было сгенерировано изображение. "
    elif file_type == "audio":
        attachment_info = "В результате выполнения был сгенерирован аудиофайл. "
    elif file_type == "video":
        attachment_info = "В результате выполнения был сгенерирован видеофайл. "

    if file_type == "image":
        render_hint = (
            f"Ты можешь показать это пользователю с помощью через "
            f'"![alt-текст](attachment:{path})" '
        )
    elif file_type == "audio":
        render_hint = (
            f"Ты можешь показать это пользователю с помощью через "
            f'"[аудио](attachment:{path})" '
        )
    elif file_type == "video":
        render_hint = (
            f"Ты можешь показать это пользователю с помощью через "
            f'"[видео](attachment:{path})" '
        )
    else:
        render_hint = (
            f"Ты можешь показать это пользователю с помощью через "
            f'"![alt-текст](attachment:{path})" '
        )

    attachment_info += f"Путь до него '{path}'. {render_hint}"
    return attachment_info


def get_user_secrets_code(user: UserShort):
    user_secrets = user.settings["contextSecrets"]
    if not user_secrets:
        return None
    code_parts = []
    for user_secret in user_secrets:
        name = user_secret.get("name")
        value = user_secret.get("value")
        if not name or not value:
            continue
        code_parts.append(f"SECRETS['{name}'] = '{value}'")
    if not code_parts:
        return None
    return "SECRETS = {}\n" + "\n".join(code_parts)


@tool
async def python(
    code: str,
    runtime: ToolRuntime,
) -> ToolMessage:
    """Выполняет Python код в Jupyter sandbox пользователя и возвращает результат.

    Используй этот инструмент для:
    - Вычислений и математических операций
    - Анализа данных с pandas/numpy
    - Визуализации с matplotlib/seaborn
    - Работы с файлами в песочнице
    - Выполнения произвольного Python кода

    Args:
        code: Python код для выполнения в Jupyter kernel.
    """
    # Получаем user_id из конфигурации langgraph auth
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    cached_user = await cache.get(UserRepository.cache_key(owner_id))
    user = (
        UserShort.model_validate(cached_user)
        if cached_user is not None
        else None
    )
    cached_sandbox = await SandboxRepository.cache_get_pair(
        owner_id=owner_id,
        provider_id=None,
    )

    factory = await get_session_factory()
    async with factory() as session:
        if user is None:
            user = await UserRepository.get_cached_or_db(
                owner_id,
                session=session,
                use_cache=False,
            )
            if user is None:
                raise ValueError(f"User with id {user_id} not found")

        resolved = await SandboxManager.get_cached_or_db(
            owner_id=owner_id,
            session=session,
            use_cache=(cached_sandbox is not None),
        )
        manager = SandboxManager(session)
        sandbox_runtime = await manager.ensure_running_for_user(
            owner_id=owner_id,
            provider_id=resolved.provider.id,
        )

    if user is None:
        raise ValueError(f"User with id {user_id} not found")

    secrets_code = get_user_secrets_code(user)

    # Выполняем код и собираем результаты
    outputs: list[str] = []
    uploads: list[UploadFileSpec] = []
    giga_attachments: list[dict[str, Any]] = []
    upload_prefix = _resolve_upload_prefix(runtime)

    # Прокидываем kernel_id из state (создан в ReplMiddleware.before_agent)
    kernel_id = runtime.state.get("kernel_id")
    if kernel_id:
        sandbox_runtime._kernel_id = kernel_id

    if secrets_code is not None:
        async for _ in sandbox_runtime.run_code(secrets_code):
            pass

    async for chunk in sandbox_runtime.run_code(code):
        chunk_type = chunk.get("type")

        if chunk_type in ("stdout", "stderr"):
            text = chunk.get("text", "")
            if text.strip():
                if chunk_type == "stderr":
                    outputs.append(f"[stderr] {text}")
                else:
                    outputs.append(text)

        elif chunk_type == "result":
            data = chunk.get("data", {})
            # Предпочитаем text/plain представление
            if "text/plain" in data:
                outputs.append(data["text/plain"])
            elif "text/html" in data:
                outputs.append(data["text/html"])

        elif chunk_type == "error":
            ename = chunk.get("ename", "Error")
            evalue = chunk.get("evalue", "")
            traceback_lines = chunk.get("traceback", [])
            # Очищаем ANSI escape-коды из traceback
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            clean_tb = "\n".join(
                ansi_escape.sub("", line) for line in traceback_lines
            )
            outputs.append(f"Error: {ename}: {evalue}\n{clean_tb}")
        elif chunk_type == "display_data":
            data = chunk.get("data", {})
            if isinstance(data, dict):
                uploads.extend(
                    _extract_upload_specs_from_display_data(data, upload_prefix)
                )

    if uploads:
        factory = await get_session_factory()
        async with factory() as session:
            manager = SandboxManager(session)
            uploaded_files = await manager.upload_files_for_user(
                owner_id=owner_id,
                files=uploads,
            )

        if len(uploaded_files) < len(uploads):
            outputs.append(
                "Часть вложений не удалось загрузить в sandbox. "
                "Показываю только успешно загруженные файлы."
            )
        for file in uploaded_files:
            outputs.append(
                _build_attachment_info(file.file_type, file.sandbox_path)
            )
            giga_attachments.append(
                FileResponse.model_validate(file).model_dump(mode="json")
            )

    result = "\n".join(outputs).strip()
    if not result:
        data = {
            "output": "Код выполнен успешно (нет вывода).",
        }
    else:
        data = {
            "output": result,
        }
    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(
            data,
            ensure_ascii=False,
        ),
        additional_kwargs={
            "tool_attachments": giga_attachments,
            "tool_name": "python",
        },
    )
