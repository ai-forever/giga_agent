"""Инструмент анализа изображения через выбранный пользователем LLM runtime."""

from __future__ import annotations

import asyncio
import io
import json
import uuid

import httpx
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from PIL import Image, ImageOps

from giga_agent.core.db import get_session_factory
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository
from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
from giga_agent.sandbox.manager import SandboxManager


def _normalize_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower() or None


async def _download_redirect_bytes(*, url: str) -> tuple[bytes, str | None]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        mime_type = _normalize_mime_type(response.headers.get("content-type"))
        return response.content, mime_type


def _image_bytes_to_jpeg_bytes(*, image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image)

        # For animated images (e.g. GIF/WebP), analyze only the first frame.
        if getattr(image, "is_animated", False):
            try:
                image.seek(0)
            except Exception:
                pass

        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in (image.info or {})
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            rgb = background
        else:
            rgb = image.convert("RGB")

        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=95, optimize=True)
        return out.getvalue()


async def _read_file_bytes(
    *,
    owner_id: uuid.UUID,
    image_path: str,
) -> tuple[bytes, str]:
    factory = await get_session_factory()
    async with factory() as session:
        _, result = await SandboxManager(session).read_file_by_path_for_user(
            user_id=owner_id,
            sandbox_path=image_path,
        )

    if isinstance(result, RedirectResult):
        data, mime_type = await _download_redirect_bytes(url=result.url)
        return data, mime_type or "application/octet-stream"

    if isinstance(result, ContentResult):
        return result.data, result.media_type or "image/png"

    if isinstance(result, StreamResult):
        chunks: list[bytes] = []
        async for chunk in result.stream:
            chunks.append(chunk)
        return b"".join(chunks), result.media_type or "image/png"

    raise ValueError("Неподдерживаемый формат результата чтения файла.")


@tool(parse_docstring=True)
async def analyze_image(
    image_path: str,
    prompt: str,
    runtime: ToolRuntime,
) -> ToolMessage:
    """Analyze an image from sandbox path with current user's LLM.

    Args:
        image_path: Полный путь вложения в sandbox (`attachment:<path>` без префикса).
        prompt: Что нужно определить по изображению.
    """
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    image_bytes, mime_type = await _read_file_bytes(
        owner_id=owner_id,
        image_path=image_path,
    )

    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
        if user is None:
            raise ValueError(f"Пользователь {owner_id} не найден")
        if user.llm_id is None:
            raise ValueError("У пользователя не выбран llm_id")

        llm_runtime = await LLMManager.resolve_by_id(user.llm_id, session=session)

    if not llm_runtime.can_analyze_image():
        raise ValueError("Текущий LLM не поддерживает analyze_image")

    jpeg_bytes = await asyncio.to_thread(
        _image_bytes_to_jpeg_bytes, image_bytes=image_bytes
    )
    analysis_text = await llm_runtime.analyze_image(
        prompt=prompt,
        image_bytes=jpeg_bytes,
        mime_type="image/jpg",
    )

    output = f"Изображение '{image_path}' проанализировано."
    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(
            {
                "output": output,
                "analysis": analysis_text,
                "image_path": image_path,
                "model": llm_runtime.model_id,
            },
            ensure_ascii=False,
        ),
    )


# Backwards compatibility for older prompts/usages.
ask_about_image = analyze_image
