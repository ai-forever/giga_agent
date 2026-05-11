from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables.config import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserShort
from giga_agent.search_engines.base import BaseSearchEngine

SecretKey = Literal[
    "TWOGIS_TOKEN", "SALUTE_SPEECH", "SALUTE_SCOPE",
    "SUBAGENTS_LLM", "RESEARCHER_LLM"
]


@dataclass(frozen=True)
class LegacyCapabilities:
    has_llm: bool
    has_search: bool
    has_image_generator: bool
    has_twogis_token: bool
    has_salute_speech: bool
    has_salute_scope: bool


async def _get_or_create_resolver(config: RunnableConfig | dict) -> RuntimeResolver:
    """Get existing resolver from config or create one on-the-fly for subgraphs."""
    try:
        return RuntimeResolver.from_config(config)
    except ValueError:
        return await RuntimeResolver.create(config)


async def get_current_user_from_runtime(
    runtime: ToolRuntime,
    *,
    session: AsyncSession,
) -> UserShort:
    resolver = await _get_or_create_resolver(runtime.config)
    return resolver.user


def get_owner_id_from_runtime(runtime: ToolRuntime) -> uuid.UUID:
    try:
        resolver = RuntimeResolver.from_config(runtime.config)
        return resolver.user.id
    except ValueError:
        user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
        return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


def get_owner_id_from_config(config: RunnableConfig | dict) -> uuid.UUID:
    try:
        resolver = RuntimeResolver.from_config(config)
        return resolver.user.id
    except ValueError:
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        user_data = configurable.get("langgraph_auth_user", {})
        user_id = user_data.get("identity")
        if user_id is None:
            raise ValueError("langgraph_auth_user.identity отсутствует в config")
        return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


async def get_current_user_from_config(
    config: RunnableConfig | dict,
    *,
    session: AsyncSession,
) -> UserShort:
    resolver = await _get_or_create_resolver(config)
    return resolver.user


def get_user_secret(user: UserShort, key: SecretKey) -> str | None:
    raw_secrets = getattr(user, "secrets", None)
    secrets = raw_secrets if isinstance(raw_secrets, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


async def resolve_user_llm(
    user: UserShort,
    *,
    session: AsyncSession,
) -> BaseChatModel:
    llm_id = user.llm_id
    subagents_llm_id = get_user_secret(user, "SUBAGENTS_LLM")
    if subagents_llm_id is not None:
        try:
            llm_id = uuid.UUID(subagents_llm_id)
        except ValueError:
            llm_id = user.llm_id

    if llm_id is None:
        raise ValueError("У пользователя не выбран llm_id")
    runtime = await LLMManager.resolve_by_id(llm_id, session=session)
    return await runtime.get_llm()


async def resolve_user_search_engine(
    user: UserShort,
    *,
    session: AsyncSession,
) -> BaseSearchEngine:
    from giga_agent.search_engines.manager import SearchEngineManager

    if user.search_engine_id is None:
        raise ValueError("У пользователя не выбран search_engine_id")
    return await SearchEngineManager.resolve_by_id(
        user.search_engine_id,
        session=session,
    )


async def resolve_user_image_generator(
    user: UserShort,
    *,
    session: AsyncSession,
) -> BaseImageGenerator:
    from giga_agent.generators.image.manager import ImageGeneratorManager

    if user.image_generator_id is None:
        raise ValueError("У пользователя не выбран image_generator_id")
    return await ImageGeneratorManager.resolve_by_id(
        user.image_generator_id,
        session=session,
    )


def get_legacy_capabilities(user: UserShort) -> LegacyCapabilities:
    return LegacyCapabilities(
        has_llm=(
            user.llm_id is not None
            or get_user_secret(user, "SUBAGENTS_LLM") is not None
        ),
        has_search=user.search_engine_id is not None,
        has_image_generator=user.image_generator_id is not None,
        has_twogis_token=get_user_secret(user, "TWOGIS_TOKEN") is not None,
        has_salute_speech=get_user_secret(user, "SALUTE_SPEECH") is not None,
        has_salute_scope=get_user_secret(user, "SALUTE_SCOPE") is not None,
    )


def with_auth_from_runtime(runtime: ToolRuntime, *, thread_id: str) -> dict:
    configurable = dict(runtime.config.get("configurable", {}))
    configurable["thread_id"] = thread_id
    return {"configurable": configurable}


def normalize_search_result(item: dict[str, Any]) -> str:
    query = str(item.get("query", "")).strip()
    result = item.get("result")
    if isinstance(result, dict):
        answer = str(result.get("answer", "")).strip()
        if answer:
            return answer
        content = str(result.get("content", "")).strip()
        if content:
            return content
    text = str(result).strip()
    return text if text else query
