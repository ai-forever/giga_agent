from __future__ import annotations

import uuid

from langchain_core.runnables import RunnableConfig

from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver, RuntimeResolver
from giga_agent.memory.backends import get_backend
from giga_agent.memory.service import MemoryService
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

_CLI_EMBEDDING_NAMESPACE = uuid.UUID("8b0e1f6a-1d80-4a4f-8a25-2d4f1bda9c10")


def get_memory_tags(config: RunnableConfig | None) -> list[str]:
    if config is None:
        return []
    configurable = config.get("configurable") or {}
    raw = configurable.get("memory_tags")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, str) and t]


def get_memory_show_global(config: RunnableConfig | None, *, tags: list[str]) -> bool:
    """If no tags → always show global. Otherwise honor the explicit flag."""
    if not tags:
        return True
    if config is None:
        return False
    configurable = config.get("configurable") or {}
    return bool(configurable.get("memory_show_global", True))


def is_memory_disabled(config: RunnableConfig | None) -> bool:
    if config is None:
        return False
    configurable = config.get("configurable") or {}
    return configurable.get("memory_disabled") is True


def get_owner_id_from_config(config: RunnableConfig) -> uuid.UUID:
    identity = get_user_id_from_config(config)
    if identity is None:
        raise ValueError("langgraph_auth_user.identity is missing from config")
    return uuid.UUID(identity) if isinstance(identity, str) else identity


def _derive_cli_embedding_id(resolver: CliRuntimeResolver) -> uuid.UUID | None:
    conf_emb = getattr(resolver, "_conf", None)
    conf_emb = getattr(conf_emb, "embedding", None) if conf_emb else None
    if conf_emb is None:
        return None
    key = f"{conf_emb.type}|{conf_emb.model_id}|{conf_emb.vector_size}"
    return uuid.uuid5(_CLI_EMBEDDING_NAMESPACE, key)


def get_embedding_id(resolver: RuntimeResolver) -> uuid.UUID | None:
    if isinstance(resolver, CliRuntimeResolver):
        return _derive_cli_embedding_id(resolver)
    return resolver.user.embedding_id


async def build_memory_service(
    config: RunnableConfig,
    *,
    include_fast_llm: bool = True,
) -> MemoryService:
    """Construct a MemoryService for the current request.

    Embeddings are optional — when the user has none configured the service
    operates in listing-only mode (no indexing/search).
    """
    try:
        resolver = RuntimeResolver.from_config(config)
    except ValueError:
        resolver = await RuntimeResolver.create(config)
        resolver.inject(config)

    owner_id = resolver.user.id
    backend = get_backend()

    embedding_runtime = None
    embedding_id = None
    if resolver.has_embedding:
        try:
            embedding_runtime = await resolver.get_embedding_runtime()
            embedding_id = get_embedding_id(resolver)
        except Exception:
            embedding_runtime = None
            embedding_id = None

    fast_llm = None
    if include_fast_llm and resolver.has_fast_llm:
        try:
            fast_llm_runtime = await resolver.get_fast_llm_runtime()
            fast_llm = await fast_llm_runtime.get_llm()
        except Exception:
            fast_llm = None

    return MemoryService(
        backend=backend,
        owner_id=owner_id,
        embedding_runtime=embedding_runtime,
        embedding_id=embedding_id,
        fast_llm=fast_llm,
    )


async def build_memory_service_for_user(
    user,
    *,
    include_fast_llm: bool = False,
):
    """Build a ``MemoryService`` directly from a user (no RunnableConfig).

    Used by REST API handlers that operate on behalf of the authenticated
    user but outside of an agent run.
    """
    from giga_agent.core.db import get_session_factory
    from giga_agent.embeddings.manager import EmbeddingManager
    from giga_agent.llm.manager import LLMManager

    backend = get_backend()

    embedding_runtime = None
    embedding_id = None
    if getattr(user, "embedding_id", None) is not None:
        try:
            factory = await get_session_factory()
            async with factory() as session:
                embedding_runtime = await EmbeddingManager.resolve_by_id(
                    user.embedding_id, session=session
                )
            embedding_id = user.embedding_id
        except Exception:
            embedding_runtime = None
            embedding_id = None

    fast_llm = None
    if include_fast_llm:
        llm_id = getattr(user, "fast_llm_id", None) or getattr(user, "llm_id", None)
        if llm_id is not None:
            try:
                factory = await get_session_factory()
                async with factory() as session:
                    llm_runtime = await LLMManager.resolve_by_id(
                        llm_id, session=session
                    )
                fast_llm = await llm_runtime.get_llm()
            except Exception:
                fast_llm = None

    return MemoryService(
        backend=backend,
        owner_id=user.id,
        embedding_runtime=embedding_runtime,
        embedding_id=embedding_id,
        fast_llm=fast_llm,
    )


__all__ = [
    "build_memory_service",
    "build_memory_service_for_user",
    "get_memory_tags",
    "get_memory_show_global",
    "is_memory_disabled",
    "get_owner_id_from_config",
    "get_embedding_id",
]
