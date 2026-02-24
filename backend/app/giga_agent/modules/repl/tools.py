"""Инструменты REPL модуля для выполнения Python кода в sandbox."""

from __future__ import annotations

import base64
import binascii
import inspect
import json
import keyword
import re
import traceback
import uuid
from typing import Any
import types

from cashews import cache
from giga_agent.core.agent.tool_node import AgentToolNode
from giga_agent.modules.repl.args_monkey_patch import _parse_input
from langchain.tools import tool, ToolRuntime
from langchain_core.tools import BaseTool
from langchain_core.messages import ToolMessage
from pydantic import ValidationError, BaseModel, Field

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models import UserShort, UserRepository
from giga_agent.models.file import FileResponse
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec

logger = get_logger(__name__)

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

_REPL_TOOL_INPUT_PREFIX = "__GIGA_REPL_TOOL_CALL__:"


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
    user_secrets = dict(user.settings or {}).get("contextSecrets")
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


def _is_tool_public_for_repl(tool_: BaseTool) -> bool:
    extras = getattr(tool_, "extras", None) or {}
    return not bool(extras.get("repl_skip"))


def _tool_accepts_parameter(tool_or_callable: Any, param_name: str) -> bool:
    candidate = tool_or_callable
    if isinstance(tool_or_callable, BaseTool):
        candidate = (
            getattr(tool_or_callable, "coroutine", None)
            or getattr(tool_or_callable, "func", None)
            or tool_or_callable
        )
    try:
        signature = inspect.signature(candidate)
    except (TypeError, ValueError):
        return False
    return param_name in signature.parameters


def _is_valid_python_identifier(name: str) -> bool:
    return bool(name and name.isidentifier() and not keyword.iskeyword(name))


def _extract_repl_tools_map() -> dict[str, Any]:
    repl_tools_map: dict[str, Any] = {}
    extras = getattr(python, "extras", None) or {}
    repl_tools = extras.get("repl_tools", [])
    if not isinstance(repl_tools, list):
        return repl_tools_map
    for repl_tool in repl_tools:
        tool_name = getattr(repl_tool, "__name__", None)
        if isinstance(tool_name, str) and tool_name:
            repl_tools_map[tool_name] = repl_tool
    return repl_tools_map


def _extract_tool_node_tools_map(
    tool_node: AgentToolNode | None,
) -> dict[str, BaseTool]:
    if tool_node is None:
        return {}

    node_runtime = getattr(tool_node, "tool_node", None)
    tools_by_name = getattr(node_runtime, "tools_by_name", None)
    if not isinstance(tools_by_name, dict):
        return {}

    tool_node_tools: dict[str, BaseTool] = {}
    for tool_name, tool_ in tools_by_name.items():
        if not isinstance(tool_name, str) or not isinstance(tool_, BaseTool):
            continue
        if tool_name == "python":
            continue
        if not _is_tool_public_for_repl(tool_):
            continue
        tool_node_tools[tool_name] = tool_
    return tool_node_tools


def _build_repl_prelude(tool_names: list[str]) -> str:
    if not tool_names:
        return ""

    prelude_lines = [
        "import json as _giga_repl_json",
        f"_GIGA_REPL_INPUT_PREFIX = {_REPL_TOOL_INPUT_PREFIX!r}",
        "",
        "def _giga_repl_call(_tool_name, **kwargs):",
        "    payload = {",
        "        'type': 'tool_call',",
        "        'tool_name': _tool_name,",
        "        'kwargs': kwargs,",
        "    }",
        "    raw_response = input(",
        "        _GIGA_REPL_INPUT_PREFIX + _giga_repl_json.dumps(payload, ensure_ascii=False)",
        "    )",
        "    response = _giga_repl_json.loads(raw_response)",
        "    if not response.get('ok'):",
        "        error = response.get('error', {})",
        "        error_type = error.get('type', 'ToolError')",
        "        error_message = error.get('message', 'Tool execution failed')",
        "        details = error.get('details', '')",
        "        full_message = f'{error_type}: {error_message}'",
        "        if details:",
        "            full_message = f'{full_message}\\n{details}'",
        "        raise RuntimeError(full_message)",
        "    return response.get('data')",
        "",
        "def _giga_repl_tool(_tool_name):",
        "    def _decorator(_func):",
        "        def _wrapper(*args, **kwargs):",
        "            if args:",
        "                raise TypeError(",
        "                    f\"Tool '{_tool_name}' accepts keyword arguments only\"",
        "                )",
        "            return _giga_repl_call(_tool_name, **kwargs)",
        "        return _wrapper",
        "    return _decorator",
        "",
    ]

    for tool_name in tool_names:
        if not _is_valid_python_identifier(tool_name):
            continue
        prelude_lines.extend(
            [
                f"@_giga_repl_tool({tool_name!r})",
                f"def {tool_name}(**kwargs):",
                "    pass",
                "",
            ]
        )

    return "\n".join(prelude_lines).rstrip() + "\n\n"


def _inject_repl_prelude(
    code: str,
    repl_tools_map: dict[str, Any],
    tool_node_tools_map: dict[str, BaseTool],
) -> str:
    tool_names = list(repl_tools_map.keys())
    for tool_name in tool_node_tools_map.keys():
        if tool_name not in repl_tools_map:
            tool_names.append(tool_name)
    prelude = _build_repl_prelude(tool_names)
    return prelude + code if prelude else code


def _parse_special_input(prompt: str) -> dict[str, Any] | None:
    if not isinstance(prompt, str):
        return None
    if not prompt.startswith(_REPL_TOOL_INPUT_PREFIX):
        return None
    raw_payload = prompt[len(_REPL_TOOL_INPUT_PREFIX) :]
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_repl_tool_result(result: Any) -> Any:
    if isinstance(result, ToolMessage):
        content = result.content
        if isinstance(content, str):
            try:
                return json.loads(content)
            except (TypeError, ValueError):
                return content
        return content
    return result


def _build_error_envelope(exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "details": traceback.format_exc(),
        },
    }


async def _invoke_repl_tool_callable(
    tool_callable: Any,
    kwargs: dict[str, Any],
    runtime: ToolRuntime,
) -> Any:
    call_kwargs = dict(kwargs)
    if _tool_accepts_parameter(tool_callable, "tool_runtime"):
        call_kwargs.setdefault("tool_runtime", runtime)
    result = tool_callable(**call_kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _invoke_tool_node_tool(
    tool_: BaseTool,
    kwargs: dict[str, Any],
    runtime: ToolRuntime,
) -> Any:
    call_kwargs = dict(kwargs)
    if _tool_accepts_parameter(tool_, "runtime"):
        call_kwargs.setdefault("runtime", runtime)
    try:
        return await tool_.ainvoke(call_kwargs, config=runtime.config)
    except ValidationError:
        raw_callable = getattr(tool_, "coroutine", None) or getattr(tool_, "func", None)
        if raw_callable is None:
            raise
        result = raw_callable(**call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result


async def _handle_special_input_request(
    prompt: str,
    runtime: ToolRuntime,
    repl_tools_map: dict[str, Any],
    tool_node_tools_map: dict[str, BaseTool],
) -> str:
    payload = _parse_special_input(prompt)
    if payload is None:
        return ""

    try:
        if payload.get("type") != "tool_call":
            raise ValueError("Unsupported input payload type")

        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Tool name is missing in input payload")

        raw_kwargs = payload.get("kwargs", {})
        if not isinstance(raw_kwargs, dict):
            raise ValueError("Tool kwargs must be a JSON object")

        if tool_name in repl_tools_map:
            raw_result = await _invoke_repl_tool_callable(
                repl_tools_map[tool_name], raw_kwargs, runtime
            )
        elif tool_name in tool_node_tools_map:
            raw_result = await _invoke_tool_node_tool(
                tool_node_tools_map[tool_name], raw_kwargs, runtime
            )
        else:
            raise ValueError(f"Tool '{tool_name}' is not available in REPL environment")

        payload_result = {"ok": True, "data": _normalize_repl_tool_result(raw_result)}
        return json.dumps(payload_result, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(_build_error_envelope(exc), ensure_ascii=False, default=str)


class PythonArgsSchema(BaseModel):
    code: str = Field(description="Python код для выполнения в Jupyter kernel.")


@tool(extras={"repl_save": False, "args_hack": True}, args_schema=PythonArgsSchema)
async def python(
    code: str,
    runtime: ToolRuntime,
    tool_node: AgentToolNode,
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
    user = UserShort.model_validate(cached_user) if cached_user is not None else None
    factory = await get_session_factory()
    async with factory() as session:
        if user is None:
            user = await UserRepository(session).get_by_id(
                owner_id,
                use_cache=False,
            )
            if user is None:
                raise ValueError(f"User with id {user_id} not found")

        resolved = await SandboxManager.get_cached_or_db(
            owner_id=owner_id,
            session=session,
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
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    repl_tools_map = _extract_repl_tools_map()
    tool_node_tools_map = _extract_tool_node_tools_map(tool_node)
    prepared_code = _inject_repl_prelude(code, repl_tools_map, tool_node_tools_map)

    # Прокидываем kernel_id из state (создан в ReplMiddleware.before_agent)
    kernel_id = runtime.state.get("kernel_id")
    if kernel_id:
        sandbox_runtime._kernel_id = kernel_id

    if secrets_code is not None:
        async for _ in sandbox_runtime.run_code(secrets_code):
            pass

    code_iter = sandbox_runtime.run_code(prepared_code)
    pending_input_reply: str | None = None
    while True:
        try:
            if pending_input_reply is None:
                chunk = await anext(code_iter)
            else:
                chunk = await code_iter.asend(pending_input_reply)
                pending_input_reply = None
        except StopAsyncIteration:
            break

        chunk_type = chunk.get("type")

        if chunk_type == "input_request":
            pending_input_reply = await _handle_special_input_request(
                prompt=str(chunk.get("prompt", "")),
                runtime=runtime,
                repl_tools_map=repl_tools_map,
                tool_node_tools_map=tool_node_tools_map,
            )
            continue

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
            clean_tb = "\n".join(ansi_escape.sub("", line) for line in traceback_lines)
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
            outputs.append(_build_attachment_info(file.file_type, file.sandbox_path))
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


# Делаем грязный хак для нормальной работы python
python._parse_input = types.MethodType(_parse_input, python)


@tool(parse_docstring=True, extras={"repl_save": False})
async def shell(
    command: str,
    runtime: ToolRuntime,
):
    """Выполняет Shell-команду в Jupyter ноутбуке.
    Используй, если нужно выполнить shell-команду в виртуальное окружение. Также обязательно используй, если нужно что-то установить из pipy.

    Args:
        command: Shell-команда

    """
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    factory = await get_session_factory()
    async with factory() as session:
        resolved = await SandboxManager.get_cached_or_db(
            owner_id=owner_id,
            session=session,
        )
        manager = SandboxManager(session)
        sandbox_runtime = await manager.ensure_running_for_user(
            owner_id=owner_id,
            provider_id=resolved.provider.id,
        )

    command = command.strip()
    if not command:
        data = {"output": "Пустая команда: передайте непустую shell-команду."}
        return ToolMessage(
            tool_call_id=runtime.tool_call_id,
            content=json.dumps(data, ensure_ascii=False),
            additional_kwargs={"tool_name": "shell"},
        )

    kernel_id = runtime.state.get("kernel_id")
    if kernel_id:
        sandbox_runtime._kernel_id = kernel_id

    shell_code = f"!{command}" if "\n" not in command else f"%%bash\n{command}"
    outputs: list[str] = []
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async for chunk in sandbox_runtime.run_code(shell_code):
        chunk_type = chunk.get("type")
        if chunk_type in ("stdout", "stderr"):
            text = chunk.get("text", "")
            if text.strip():
                clean_text = ansi_escape.sub("", text)
                outputs.append(
                    f"[stderr] {clean_text}" if chunk_type == "stderr" else clean_text
                )
        elif chunk_type == "result":
            data = chunk.get("data", {})
            if "text/plain" in data:
                outputs.append(str(data["text/plain"]))
            elif "text/html" in data:
                outputs.append(str(data["text/html"]))
        elif chunk_type == "error":
            ename = chunk.get("ename", "Error")
            evalue = chunk.get("evalue", "")
            traceback_lines = chunk.get("traceback", [])
            clean_tb = "\n".join(ansi_escape.sub("", line) for line in traceback_lines)
            outputs.append(f"Error: {ename}: {evalue}\n{clean_tb}")

    result = "\n".join(outputs).strip()
    data = {"output": result or "Команда выполнена успешно (нет вывода)."}

    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(data, ensure_ascii=False),
        additional_kwargs={"tool_name": "shell"},
    )
