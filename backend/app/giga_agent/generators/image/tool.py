"""LangChain tool для генерации изображений.

Резолвит текущий генератор пользователя по `User.image_generator_id`,
генерирует картинку, загружает в sandbox и возвращает путь.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any

from langchain.tools import tool, ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_gigachat import GigaChat
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session_factory
from giga_agent.generators.image.base import BaseImageGenerator, DEFAULT_WIDTH, DEFAULT_HEIGHT
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.models import UserShort, UserRepository, LLMProviderRepository
from giga_agent.models.image_generator import (
    ImageGeneratorRepository,
    ImageGenerator,
    ImageGeneratorResponse,
)
from giga_agent.models.file import FileResponse
from giga_agent.sandbox.manager import SandboxManager, UploadFileSpec

logger = logging.getLogger(__name__)

# Убедимся, что провайдеры зарегистрированы
import giga_agent.generators.image  # noqa: F401


def _build_llm_from_provider(provider_type: str, settings: dict[str, Any]) -> BaseChatModel:
    provider_type_normalized = provider_type.lower()
    kwargs = LLMProviderRepository.get_connection_kwargs(provider_type_normalized, settings)
    if kwargs is None:
        raise ValueError(
            f"Invalid connection settings for llm provider type '{provider_type_normalized}'"
        )

    if provider_type_normalized == "openai":
        return ChatOpenAI(**kwargs)
    if provider_type_normalized == "gigachat":
        return GigaChat(**kwargs)

    raise ValueError(
        f"Unsupported llm provider type for image generator: '{provider_type_normalized}'"
    )


async def _resolve_llm_for_image_generator(
    *,
    owner_id: uuid.UUID,
    record: ImageGenerator | ImageGeneratorResponse,
    session: AsyncSession,
    runtime_cls: type[BaseImageGenerator],
) -> BaseChatModel | None:
    supported_types = [t.lower() for t in runtime_cls.supported_llm_provider_types()]
    if record.llm_provider_id is None:
        return None
    if not supported_types:
        raise ValueError(
            f"Image generator '{record.type}' does not support llm providers."
        )

    provider_repo = LLMProviderRepository(session)
    provider = await provider_repo.get_by_id(record.llm_provider_id)
    if provider is None:
        raise ValueError(f"LLM provider {record.llm_provider_id} not found")
    if provider.owner_id != owner_id:
        raise ValueError(
            f"LLM provider {provider.id} does not belong to user {owner_id}."
        )
    if not provider.is_active:
        raise ValueError(f"LLM provider {provider.id} is inactive.")

    provider_type = (provider.type or "").lower()
    if provider_type not in supported_types:
        raise ValueError(
            f"LLM provider type '{provider_type}' is not supported by "
            f"image generator '{record.type}'. Supported types: {supported_types}"
        )

    return _build_llm_from_provider(provider_type, provider.settings or {})


async def _resolve_generator_for_user(
    owner_id: uuid.UUID,
    user: UserShort,
) -> BaseImageGenerator:
    """
    Загружает из БД запись ImageGenerator по `user.image_generator_id`,
    создаёт и инициализирует runtime-экземпляр генератора.
    """
    gen_id = user.image_generator_id
    if gen_id is None:
        raise ValueError(
            "У пользователя не выбран генератор изображений. "
            "Установите image_generator_id в настройках пользователя."
        )

    factory = await get_session_factory()
    async with factory() as session:
        record = await ImageGeneratorRepository.get_cached_or_db(
            gen_id,
            session=session,
            use_cache=True,
        )
        if record is None:
            raise ValueError(f"Генератор изображений {gen_id} не найден.")
        if record.owner_id != owner_id:
            raise ValueError(
                f"Генератор изображений {gen_id} не принадлежит пользователю {owner_id}."
            )
        if not record.is_active:
            raise ValueError(
                f"Генератор изображений {gen_id} неактивен."
            )

        runtime_cls = ImageGeneratorRegistry.get(record.type)
        llm = await _resolve_llm_for_image_generator(
            owner_id=owner_id,
            record=record,
            session=session,
            runtime_cls=runtime_cls,
        )

    generator = runtime_cls(
        **(record.settings or {}),
        llm=llm,
    )
    await generator.init()
    return generator


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
    """Генерирует изображение по описанию и сохраняет в sandbox пользователя.

    Args:
        prompt: Описание изображения для генерации.
        width: Ширина изображения в пикселях (по умолчанию 1024).
        height: Высота изображения в пикселях (по умолчанию 1024).
    """
    # 1. Получаем owner_id из конфигурации langgraph auth
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    # 2. Загружаем пользователя
    user = await UserRepository.get_cached_or_db(owner_id)
    if user is None:
        raise ValueError(f"Пользователь {user_id} не найден")

    # 3. Резолвим генератор по image_generator_id
    generator = await _resolve_generator_for_user(owner_id, user)

    # 4. Генерируем изображение
    image_b64 = await generator.generate_image(prompt, width, height)

    # 5. Загружаем в sandbox
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
            owner_id=owner_id,
            files=upload_files,
        )

    if not uploaded:
        raise RuntimeError("Не удалось загрузить сгенерированное изображение в sandbox.")

    file = uploaded[0]
    sandbox_path = file.sandbox_path

    # 6. Формируем ответ
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
        content=json.dumps(
            {"output": result_text},
            ensure_ascii=False,
        ),
        additional_kwargs={
            "tool_attachments": giga_attachments,
            "tool_name": "gen_image",
        },
    )
