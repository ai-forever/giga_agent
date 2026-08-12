"""Инструмент анализа изображения через выбранный пользователем LLM runtime."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from PIL import Image, ImageOps
from plotly import io as plotly_io
from pydantic import Field

from giga_agent.conf import get_settings
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.db import get_session_factory
from giga_agent.llm.base import BaseLLMRuntime, ImageInput
from giga_agent.sandbox.base import RedirectResult
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.sandbox.materialize import materialize_bounded
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

# Максимальный размер изображения, скачиваемого по ссылке.
MAX_URL_IMAGE_BYTES = 9 * 1024 * 1024
MAX_ANALYZE_IMAGES = 4


def _is_http_url(value: str) -> bool:
    return urlsplit(value).scheme in {"http", "https"}


async def resolve_image_analyzer_llm(
    resolver: RuntimeResolver,
) -> BaseLLMRuntime | None:
    """Pick an LLM runtime that supports image analysis.

    Priority: primary ``llm`` first, then ``fast_llm``.
    """
    if resolver.has_llm:
        try:
            llm = await resolver.get_llm_runtime()
            if llm.can_analyze_images():
                return llm
        except Exception:
            pass
    if resolver.has_fast_llm:
        try:
            fast_llm = await resolver.get_fast_llm_runtime()
            if fast_llm.can_analyze_images():
                return fast_llm
        except Exception:
            pass
    return None


def _normalize_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower() or None


async def _download_image_bytes(
    *, url: str, max_bytes: int = MAX_URL_IMAGE_BYTES
) -> tuple[bytes, str | None]:
    """Скачать изображение по ссылке, не превышая ``max_bytes``."""
    limit_mb = max_bytes // (1024 * 1024)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit():
                if int(content_length) > max_bytes:
                    raise ValueError(f"Изображение по ссылке больше {limit_mb} МБ.")

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Изображение по ссылке больше {limit_mb} МБ.")
                chunks.append(chunk)

            mime_type = _normalize_mime_type(response.headers.get("content-type"))
            return b"".join(chunks), mime_type


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
    runtime: ToolRuntime | None = None,
) -> tuple[bytes, str]:
    if get_settings().giga_agent_runtime == "cli":
        if runtime is None:
            raise ValueError("ToolRuntime is required in CLI mode")
        resolver = RuntimeResolver.from_config(runtime.config)
        resolved = await resolver.get_sandbox()
        sandbox = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
        result = await sandbox.read_file(image_path)
    else:
        factory = await get_session_factory()
        async with factory() as session:
            _, result = await SandboxManager(session).read_file_by_path_for_user(
                user_id=owner_id,
                sandbox_path=image_path,
            )

    data, too_large = await materialize_bounded(result, MAX_URL_IMAGE_BYTES)
    if too_large:
        limit_mb = MAX_URL_IMAGE_BYTES // (1024 * 1024)
        raise ValueError(f"Изображение больше {limit_mb} МБ.")
    if data is None:
        raise ValueError("Неподдерживаемый формат результата чтения файла.")

    if isinstance(result, RedirectResult):
        return data, "application/octet-stream"
    return data, getattr(result, "media_type", None) or "image/png"


async def _prepare_image(
    *,
    owner_id: uuid.UUID,
    image_path: str,
    runtime: ToolRuntime | None = None,
) -> ImageInput:
    try:
        if _is_http_url(image_path):
            image_bytes, mime_type = await _download_image_bytes(url=image_path)
        else:
            image_bytes, mime_type = await _read_file_bytes(
                owner_id=owner_id,
                image_path=image_path,
                runtime=runtime,
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

        jpeg_bytes = await asyncio.to_thread(
            _image_bytes_to_jpeg_bytes, image_bytes=image_bytes
        )
        return {"image_bytes": jpeg_bytes, "mime_type": "image/jpg"}
    except Exception as exc:
        raise ValueError(
            f"Не удалось подготовить изображение '{image_path}': {exc}"
        ) from exc


async def _prepare_images(
    *,
    owner_id: uuid.UUID,
    image_paths: list[str],
    runtime: ToolRuntime | None = None,
) -> list[ImageInput]:
    tasks = [
        asyncio.create_task(
            _prepare_image(
                owner_id=owner_id,
                image_path=image_path,
                runtime=runtime,
            )
        )
        for image_path in image_paths
    ]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def analyze_image(
    image_paths: Annotated[list[str], Field(min_length=1, max_length=MAX_ANALYZE_IMAGES)],
    prompt: str,
    runtime: ToolRuntime,
) -> ToolMessage:
    """Analyze one to four images from sandbox paths or URLs with current user's LLM.

    Args:
        image_paths: Пути вложений в sandbox (`attachment:<path>` без префикса) либо
            прямые ссылки http(s) на изображения (максимум 9 МБ на изображение).
        prompt: Что нужно определить по изображениям.
    """
    if not 1 <= len(image_paths) <= MAX_ANALYZE_IMAGES:
        raise ValueError(
            f"analyze_image принимает от 1 до {MAX_ANALYZE_IMAGES} изображений."
        )

    resolver = RuntimeResolver.from_config(runtime.config)
    owner_id = resolver.user.id
    images = await _prepare_images(
        owner_id=owner_id,
        image_paths=image_paths,
        runtime=runtime,
    )

    llm_runtime = await resolve_image_analyzer_llm(resolver)

    if llm_runtime is None:
        raise ValueError("Текущий LLM не поддерживает анализ нескольких изображений")

    analysis_text = await llm_runtime.analyze_images(prompt=prompt, images=images)

    output = (
        f"Изображение '{image_paths[0]}' проанализировано."
        if len(image_paths) == 1
        else f"Проанализировано изображений: {len(image_paths)}."
    )
    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps(
            {
                "output": output,
                "analysis": analysis_text,
                "image_paths": image_paths,
                "model": llm_runtime.model_id,
            },
            ensure_ascii=False,
        ),
    )


# Backwards compatibility for older prompts/usages.
ask_about_image = analyze_image
