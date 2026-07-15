"""LangChain tool for image generation.

Resolves current user's image generator via `User.image_generator_id`,
generates image, uploads to sandbox and returns path.
"""

from __future__ import annotations

import base64
import json
import uuid

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.generators.image.base import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    BaseImageGenerator,
)
from giga_agent.models.file import FileResponse
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec

logger = get_logger(__name__)

# ruff: noqa: E402

# Ensure providers are registered.
import giga_agent.generators.image  # noqa: F401


async def _resolve_generator(runtime: ToolRuntime) -> BaseImageGenerator:
    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    resolver = RuntimeResolver.from_config(runtime.config)
    if not resolver.has_image_generator:
        raise ValueError(
            "У пользователя не выбран генератор изображений. "
            "Настройте image_generator в runtime."
        )
    return await resolver.get_image_generator()


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


@tool(parse_docstring=True, extras={"repl_save": False})
async def gen_image(
    prompt: str,
    runtime: ToolRuntime,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> ToolMessage:
    """Generate image from prompt and upload to user sandbox.

    Args:
        prompt: Image generation prompt.
        width: Image width in pixels (default 1024).
        height: Image height in pixels (default 1024).
    """
    owner_id = _resolve_owner_id(runtime)
    generator = await _resolve_generator(runtime)

    try:
        image_b64 = await generator.generate_image(prompt, width, height)
    finally:
        await generator.cleanup()

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
        manager = SandboxManager(session)
        uploaded = await manager.upload_files_for_user(
            user_id=owner_id,
            files=upload_files,
        )

    if not uploaded.files:
        raise RuntimeError(
            "Не удалось загрузить сгенерированное изображение в sandbox."
        )

    file = uploaded.files[0]
    sandbox_path = file.sandbox_path

    render_hint = f'Покажи это пользователю через "![описание изображения](attachment:{sandbox_path})"'
    result_text = (
        f"Изображение успешно сгенерировано. Путь: '{sandbox_path}'. {render_hint}"
    )

    giga_attachments = [FileResponse.model_validate(file).model_dump(mode="json")]

    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps({"output": result_text}, ensure_ascii=False),
        additional_kwargs={
            "tool_attachments": giga_attachments,
            "tool_name": "gen_image",
        },
    )
