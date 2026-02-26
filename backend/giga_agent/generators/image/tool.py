"""LangChain tool for image generation.

Resolves current user's image generator via `User.image_generator_id`,
generates image, uploads to sandbox and returns path.
"""

from __future__ import annotations

import base64
import json
import uuid

from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.generators.image.base import BaseImageGenerator, DEFAULT_WIDTH, DEFAULT_HEIGHT
from giga_agent.generators.image.manager import ImageGeneratorManager
from giga_agent.models import UserShort, UserRepository
from giga_agent.models.file import FileResponse
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec

logger = get_logger(__name__)

# Ensure providers are registered.
import giga_agent.generators.image  # noqa: F401


async def _resolve_generator_for_user(
    user: UserShort,
    *,
    session: AsyncSession,
) -> BaseImageGenerator:
    """
    Load ImageGenerator record by `user.image_generator_id`,
    create and initialize runtime instance.
    """
    gen_id = user.image_generator_id
    if gen_id is None:
        raise ValueError(
            "У пользователя не выбран генератор изображений. "
            "Установите image_generator_id в настройках пользователя."
        )

    return await ImageGeneratorManager.resolve_by_id(gen_id, session=session)


def _resolve_upload_prefix(runtime: ToolRuntime) -> str:
    configurable = runtime.config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str):
        clean = thread_id.strip().strip("/")
        if clean:
            return clean
    return f"temporary/{uuid.uuid4().hex}"


@tool
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
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
        if user is None:
            raise ValueError(f"Пользователь {user_id} не найден")

        generator = await _resolve_generator_for_user(user, session=session)

    image_b64 = await generator.generate_image(prompt, width, height)

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

    async with factory() as session:
        manager = SandboxManager(session)
        uploaded = await manager.upload_files_for_user(
            owner_id=owner_id,
            files=upload_files,
        )

    if not uploaded:
        raise RuntimeError("Не удалось загрузить сгенерированное изображение в sandbox.")

    file = uploaded[0]
    sandbox_path = file.sandbox_path

    render_hint = (
        f'Покажи это пользователю через "![описание изображения](attachment:{sandbox_path})"'
    )
    result_text = (
        f"Изображение успешно сгенерировано. Путь: '{sandbox_path}'. {render_hint}"
    )

    giga_attachments = [
        FileResponse.model_validate(file).model_dump(mode="json")
    ]

    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=json.dumps({"output": result_text}, ensure_ascii=False),
        additional_kwargs={
            "tool_attachments": giga_attachments,
            "tool_name": "gen_image",
        },
    )
