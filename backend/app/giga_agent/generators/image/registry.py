import logging
from typing import Type

from pydantic import BaseModel

from giga_agent.generators.image.base import BaseImageGenerator

logger = logging.getLogger(__name__)


class ImageGeneratorRegistry:
    """
    Реестр runtime-классов генераторов изображений.

    Каждый провайдер регистрируется через декоратор:

        @ImageGeneratorRegistry.register("openai")
        class OpenAIImageGen(BaseImageGenerator):
            ...

    Получить runtime-класс по типу провайдера:

        cls = ImageGeneratorRegistry.get("openai")

    Валидировать settings для провайдера:

        validated = ImageGeneratorRegistry.validate_settings("openai", {"api_key": "..."})
    """

    _registry: dict[str, Type[BaseImageGenerator]] = {}

    @classmethod
    def register(cls, provider_type: str):
        """
        Декоратор для регистрации runtime-класса генератора изображений.

        :param provider_type: Строковый идентификатор провайдера (e.g. "openai", "gigachat", "fusion_brain").
        """

        def decorator(gen_cls: Type[BaseImageGenerator]) -> Type[BaseImageGenerator]:
            if provider_type in cls._registry:
                logger.warning(
                    f"Image generator provider '{provider_type}' is already registered "
                    f"({cls._registry[provider_type].__name__}), "
                    f"overriding with {gen_cls.__name__}"
                )
            cls._registry[provider_type] = gen_cls
            return gen_cls

        return decorator

    @classmethod
    def get(cls, provider_type: str) -> Type[BaseImageGenerator]:
        """
        Получить runtime-класс по типу провайдера.

        :raises ValueError: Если провайдер не зарегистрирован.
        """
        if provider_type not in cls._registry:
            raise ValueError(
                f"Unknown image generator provider: '{provider_type}'. "
                f"Available: {cls.available_types()}"
            )
        return cls._registry[provider_type]

    @classmethod
    def get_settings_schema(cls, provider_type: str) -> Type[BaseModel]:
        """
        Получить Pydantic-модель для валидации settings конкретного провайдера.
        """
        runtime_cls = cls.get(provider_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(cls, provider_type: str, settings: dict) -> dict:
        """
        Валидировать и нормализовать settings для провайдера.

        :param provider_type: Тип провайдера ("openai", "gigachat", "fusion_brain").
        :param settings: Сырой dict настроек.
        :returns: Валидированный dict.
        :raises ValidationError: Если settings не проходят валидацию.
        :raises ValueError: Если проверка подключения не пройдена.
        """
        runtime_cls = cls.get(provider_type)
        return await runtime_cls.validate_settings(settings)

    @classmethod
    def available_types(cls) -> list[str]:
        """Список зарегистрированных типов провайдеров."""
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, provider_type: str) -> bool:
        """Проверить, зарегистрирован ли провайдер."""
        return provider_type in cls._registry
