"""Provider-specific Nano Banana image tool."""

from __future__ import annotations

import base64
import json
import mimetypes
import uuid

import httpx
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage

from giga_agent.core.db import get_session_factory
from giga_agent.generators.image.nano_banana.generator import (
    NanoBananaAspectRatio,
    NanoBananaImageGen,
)
from giga_agent.models.file import FileResponse
from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec


def _resolve_owner_id(runtime: ToolRuntime) -> uuid.UUID:
    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    resolver = RuntimeResolver.from_config(runtime.config)
    return resolver.user.id


def _resolve_upload_prefix(runtime: ToolRuntime) -> str:
    configurable = runtime.config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str):
        clean = thread_id.strip().strip("/")
        if clean:
            return clean
    return f"temporary/{uuid.uuid4().hex}"


async def _resolve_nano_banana_generator(
    runtime: ToolRuntime,
) -> tuple[uuid.UUID, NanoBananaImageGen]:
    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    resolver = RuntimeResolver.from_config(runtime.config)
    if not resolver.has_image_generator:
        raise ValueError(
            "У пользователя не выбран генератор изображений. "
            "Настройте image_generator в runtime."
        )
    generator = await resolver.get_image_generator()

    if not isinstance(generator, NanoBananaImageGen):
        raise ValueError("Текущий генератор изображений не поддерживает этот tool gen_image.")

    return resolver.user.id, generator


def _normalize_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower() or None


async def _download_redirect_bytes(*, url: str) -> tuple[bytes, str | None]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content, _normalize_mime_type(response.headers.get("content-type"))


def _normalize_sandbox_path(path: str) -> str:
    clean = (path or "").strip()
    if clean.startswith("attachment:"):
        clean = clean.removeprefix("attachment:")
    return clean


async def _read_sandbox_file_bytes(
    *,
    owner_id: uuid.UUID,
    sandbox_path: str,
) -> tuple[bytes, str]:
    normalized_path = _normalize_sandbox_path(sandbox_path)
    if not normalized_path:
        raise ValueError("Пустой sandbox path для input image.")

    factory = await get_session_factory()
    async with factory() as session:
        _, result = await SandboxManager(session).read_file_by_path_for_user(
            user_id=owner_id,
            sandbox_path=normalized_path,
        )

    guessed_mime = _normalize_mime_type(mimetypes.guess_type(normalized_path)[0])

    if isinstance(result, RedirectResult):
        data, mime_type = await _download_redirect_bytes(url=result.url)
        return data, mime_type or guessed_mime or "application/octet-stream"

    if isinstance(result, ContentResult):
        return result.data, _normalize_mime_type(result.media_type) or guessed_mime or "image/png"

    if isinstance(result, StreamResult):
        chunks: list[bytes] = []
        async for chunk in result.stream:
            chunks.append(chunk)
        return (
            b"".join(chunks),
            _normalize_mime_type(result.media_type) or guessed_mime or "image/png",
        )

    raise ValueError("Неподдерживаемый формат результата чтения файла.")


async def _resolve_input_images(
    *,
    owner_id: uuid.UUID,
    input_paths: list[str],
) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for input_path in input_paths:
        image_bytes, mime_type = await _read_sandbox_file_bytes(
            owner_id=owner_id,
            sandbox_path=input_path,
        )
        if not mime_type.startswith("image/"):
            raise ValueError(
                f"Файл '{input_path}' не является изображением (mime_type={mime_type})."
            )
        images.append(
            {
                "mime_type": mime_type,
                "content_b64": base64.b64encode(image_bytes).decode("ascii"),
            }
        )
    return images


async def _upload_generated_image(
    *,
    owner_id: uuid.UUID,
    runtime: ToolRuntime,
    image_b64: str,
) -> tuple[str, list[dict]]:
    upload_prefix = _resolve_upload_prefix(runtime)
    image_bytes = base64.b64decode(image_b64)
    file_name = f"{upload_prefix}/images/{uuid.uuid4().hex}.png"
    upload_files: list[UploadFileSpec] = [
        {
            "file_name": file_name,
            "content": image_bytes,
            "file_type": "image",
        }
    ]

    factory = await get_session_factory()
    async with factory() as session:
        uploaded = await SandboxManager(session).upload_files_for_user(
            user_id=owner_id,
            files=upload_files,
        )

    if not uploaded.files:
        raise RuntimeError("Не удалось загрузить сгенерированное изображение в sandbox.")

    file = uploaded.files[0]
    return file.sandbox_path, [FileResponse.model_validate(file).model_dump(mode="json")]


@tool(parse_docstring=True, extras={"repl_save": False})
async def gen_image(
    prompt: str,
    runtime: ToolRuntime,
    input_paths: list[str] | None = None,
    aspect_ratio: NanoBananaAspectRatio | None = None,
) -> ToolMessage:
    """Generate an image with Nano Banana from text or reference images.

    Args:
        prompt: Prompt for image generation or instruction for reference-based generation.
        input_paths: Optional image paths in sandbox used as references.
        aspect_ratio: Optional output aspect ratio. Change only if user asks for it.
    """
    owner_id, generator = await _resolve_nano_banana_generator(runtime)

    generation_kwargs: dict[str, object] = {}
    if input_paths:
        generation_kwargs["input_images"] = await _resolve_input_images(
            owner_id=owner_id,
            input_paths=input_paths,
        )
    if aspect_ratio is not None:
        generation_kwargs["aspect_ratio"] = aspect_ratio

    image_b64 = await generator.generate_image(prompt, None, None, **generation_kwargs)
    sandbox_path, giga_attachments = await _upload_generated_image(
        owner_id=owner_id,
        runtime=runtime,
        image_b64=image_b64,
    )

    render_hint = (
        f'Покажи это пользователю через "![описание изображения](attachment:{sandbox_path})"'
    )
    result_text = (
        f"Изображение успешно сгенерировано. Путь: '{sandbox_path}'. {render_hint}"
    )

    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps({"output": result_text}, ensure_ascii=False),
        additional_kwargs={
            "tool_attachments": giga_attachments,
            "tool_name": "gen_image",
        },
    )
