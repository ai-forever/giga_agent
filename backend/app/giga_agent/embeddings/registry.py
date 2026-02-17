"""Registry for embeddings runtime classes."""

from __future__ import annotations

import logging
from typing import Type

from pydantic import BaseModel

from giga_agent.embeddings.base import BaseEmbeddingRuntime

logger = logging.getLogger(__name__)


class EmbeddingRegistry:
    _registry: dict[str, Type[BaseEmbeddingRuntime]] = {}

    @classmethod
    def register(cls, embedding_type: str):
        def decorator(runtime_cls: Type[BaseEmbeddingRuntime]) -> Type[BaseEmbeddingRuntime]:
            key = (embedding_type or "").lower()
            if key in cls._registry:
                logger.warning(
                    "Embeddings runtime '%s' is already registered (%s), overriding with %s",
                    key,
                    cls._registry[key].__name__,
                    runtime_cls.__name__,
                )
            cls._registry[key] = runtime_cls
            return runtime_cls

        return decorator

    @classmethod
    def get(cls, embedding_type: str) -> Type[BaseEmbeddingRuntime]:
        key = (embedding_type or "").lower()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown embedding type: '{embedding_type}'. Available: {cls.available_types()}"
            )
        return cls._registry[key]

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, embedding_type: str) -> bool:
        return (embedding_type or "").lower() in cls._registry

    @classmethod
    def get_settings_schema(cls, embedding_type: str) -> Type[BaseModel]:
        runtime_cls = cls.get(embedding_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(
        cls,
        embedding_type: str,
        settings: dict,
    ) -> dict:
        runtime_cls = cls.get(embedding_type)
        return await runtime_cls.validate_settings(settings)
