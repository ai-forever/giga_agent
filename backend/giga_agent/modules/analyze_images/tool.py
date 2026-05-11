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
from plotly import io as plotly_io

from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.db import get_session_factory
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


def _is_json_mime_type(mime_type: str | None) -> bool:
    normalized = _normalize_mime_type(mime_type)
    return normalized in {
        "application/json",
        "application/vnd.plotly.v1+json",
        "text/json",
    }


def _is_plotly_json_input(*, mime_type: str | None, image_path: str) -> bool:
    return _is_json_mime_type(mime_type) or image_path.lower().endswith(".plotly.json")


def _looks_like_plotly_figure(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False

    data = payload.get("data")
    if not isinstance(data, list):
        return False

    layout = payload.get("layout")
    if layout is not None and not isinstance(layout, dict):
        return False

    frames = payload.get("frames")
    if frames is not None and not isinstance(frames, list):
        return False

    allowed_keys = {"data", "layout", "frames", "config"}
    return bool(set(payload).intersection({"data", "layout", "frames"})) and set(
        payload
    ).issubset(allowed_keys)


def _plotly_json_to_png_bytes(*, payload_bytes: bytes) -> bytes | None:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not _looks_like_plotly_figure(payload):
        return None

    try:
        figure = plotly_io.from_json(json.dumps(payload, ensure_ascii=False))
        return figure.to_image(format="png")
    except ValueError:
        return None


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
    resolver = RuntimeResolver.from_config(runtime.config)
    owner_id = resolver.user.id
    image_bytes, mime_type = await _read_file_bytes(
        owner_id=owner_id,
        image_path=image_path,
    )
    if _is_plotly_json_input(mime_type=mime_type, image_path=image_path):
        plotly_png_bytes = await asyncio.to_thread(
            _plotly_json_to_png_bytes, payload_bytes=image_bytes
        )
        if plotly_png_bytes is None:
            raise ValueError(
                "analyze_image поддерживает только изображения и Plotly JSON-графики."
            )
        image_bytes = plotly_png_bytes

    llm_runtime = await resolver.get_llm_runtime()

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
