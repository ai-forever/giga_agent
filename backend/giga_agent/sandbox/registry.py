import os
from typing import Type

from pydantic import BaseModel

from giga_agent.sandbox.base import BaseSandbox
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)
LOCAL_DOCKER_PROVIDER = "local_docker"


class SandboxRegistry:
    """
    Реестр runtime-классов песочниц.

    Каждый провайдер регистрируется через декоратор:

        @SandboxRegistry.register("local_docker")
        class LocalDockerSandbox(BaseSandbox):
            ...

    Получить runtime-класс по типу провайдера:

        cls = SandboxRegistry.get("local_docker")

    Валидировать settings для провайдера:

        validated = SandboxRegistry.validate_settings("e2b", {"api_key": "..."})
    """

    _registry: dict[str, Type[BaseSandbox]] = {}

    @staticmethod
    def _is_true_env(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return default

    @classmethod
    def is_provider_enabled(cls, provider_type: str) -> bool:
        if provider_type != LOCAL_DOCKER_PROVIDER:
            return True
        return cls._is_true_env("GIGA_AGENT_LOCAL_SANDBOX_ENABLED", default=False)

    @classmethod
    def register(cls, provider_type: str):
        """
        Декоратор для регистрации runtime-класса песочницы.

        :param provider_type: Строковый идентификатор провайдера (e.g. "e2b", "local_docker").
        """

        def decorator(sandbox_cls: Type[BaseSandbox]) -> Type[BaseSandbox]:
            if provider_type in cls._registry:
                logger.warning(
                    f"Sandbox provider '{provider_type}' is already registered "
                    f"({cls._registry[provider_type].__name__}), "
                    f"overriding with {sandbox_cls.__name__}"
                )
            cls._registry[provider_type] = sandbox_cls
            return sandbox_cls

        return decorator

    @classmethod
    def get(cls, provider_type: str) -> Type[BaseSandbox]:
        """
        Получить runtime-класс по типу провайдера.

        :raises ValueError: Если провайдер не зарегистрирован.
        """
        if provider_type not in cls._registry or not cls.is_provider_enabled(provider_type):
            raise ValueError(
                f"Unknown sandbox provider: '{provider_type}'. "
                f"Available: {cls.available_types()}"
            )
        return cls._registry[provider_type]

    @classmethod
    def get_settings_schema(cls, provider_type: str) -> Type[BaseModel]:
        """
        Получить Pydantic-модель для валидации settings конкретного провайдера.

        Модель генерируется автоматически из полей runtime-класса,
        исключая поля из _runtime_fields (системные).
        """
        runtime_cls = cls.get(provider_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(cls, provider_type: str, settings: dict) -> dict:
        """
        Валидировать и нормализовать settings для провайдера.

        Делегирует валидацию в BaseSandbox.validate_settings() конкретного runtime-класса.
        Может выполнять проверку реального подключения (e.g. API key, S3 bucket).

        :param provider_type: Тип провайдера ("e2b", "local_docker", ...).
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
        return [
            provider_type
            for provider_type in cls._registry.keys()
            if cls.is_provider_enabled(provider_type)
        ]

    @classmethod
    def is_registered(cls, provider_type: str) -> bool:
        """Проверить, зарегистрирован ли провайдер."""
        return provider_type in cls._registry and cls.is_provider_enabled(provider_type)
