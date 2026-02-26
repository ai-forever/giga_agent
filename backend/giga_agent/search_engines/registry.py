from typing import Type

from pydantic import BaseModel

from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class SearchEngineRegistry:
    """Реестр runtime-классов поисковых движков."""

    _registry: dict[str, Type[BaseSearchEngine]] = {}

    @classmethod
    def register(cls, engine_type: str):
        """Декоратор для регистрации runtime-класса поискового движка."""

        def decorator(engine_cls: Type[BaseSearchEngine]) -> Type[BaseSearchEngine]:
            if engine_type in cls._registry:
                logger.warning(
                    f"Search engine '{engine_type}' is already registered "
                    f"({cls._registry[engine_type].__name__}), "
                    f"overriding with {engine_cls.__name__}"
                )
            cls._registry[engine_type] = engine_cls
            return engine_cls

        return decorator

    @classmethod
    def get(cls, engine_type: str) -> Type[BaseSearchEngine]:
        """Получить runtime-класс по типу движка."""
        if engine_type not in cls._registry:
            raise ValueError(
                f"Unknown search engine provider: '{engine_type}'. "
                f"Available: {cls.available_types()}"
            )
        return cls._registry[engine_type]

    @classmethod
    def get_settings_schema(cls, engine_type: str) -> Type[BaseModel]:
        """Получить Pydantic-схему settings конкретного движка."""
        runtime_cls = cls.get(engine_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(cls, engine_type: str, settings: dict) -> dict:
        """Валидировать и нормализовать settings для движка."""
        runtime_cls = cls.get(engine_type)
        return await runtime_cls.validate_settings(settings)

    @classmethod
    def available_types(cls) -> list[str]:
        """Список зарегистрированных типов движков."""
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, engine_type: str) -> bool:
        """Проверить, зарегистрирован ли движок."""
        return engine_type in cls._registry
