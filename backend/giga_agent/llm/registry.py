"""Registry for LLM runtime classes."""

from __future__ import annotations

from typing import Type

from giga_agent.llm.base import BaseLLMRuntime
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class LLMRegistry:
    _registry: dict[str, Type[BaseLLMRuntime]] = {}

    @classmethod
    def register(cls, llm_type: str):
        def decorator(llm_cls: Type[BaseLLMRuntime]) -> Type[BaseLLMRuntime]:
            key = (llm_type or "").lower()
            if key in cls._registry:
                logger.warning(
                    "LLM runtime '%s' is already registered (%s), overriding with %s",
                    key,
                    cls._registry[key].__name__,
                    llm_cls.__name__,
                )
            cls._registry[key] = llm_cls
            llm_cls._registered_llm_type = key
            return llm_cls

        return decorator

    @classmethod
    def get(cls, llm_type: str) -> Type[BaseLLMRuntime]:
        key = (llm_type or "").lower()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown llm type: '{llm_type}'. Available: {cls.available_types()}"
            )
        return cls._registry[key]

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, llm_type: str) -> bool:
        return (llm_type or "").lower() in cls._registry
