"""Registry for connector runtime classes."""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel

from giga_agent.connectors.base import BaseConnector
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class ConnectorRegistry:
    _registry: dict[str, Type[BaseConnector]] = {}

    @classmethod
    def register(cls, connector_type: str):
        def decorator(connector_cls: Type[BaseConnector]) -> Type[BaseConnector]:
            if connector_type in cls._registry:
                logger.warning(
                    "Connector '%s' is already registered (%s), overriding with %s",
                    connector_type,
                    cls._registry[connector_type].__name__,
                    connector_cls.__name__,
                )
            cls._registry[connector_type] = connector_cls
            return connector_cls

        return decorator

    @classmethod
    def get(cls, connector_type: str) -> Type[BaseConnector]:
        key = (connector_type or "").lower()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown connector type: '{connector_type}'. "
                f"Available: {cls.available_types()}"
            )
        return cls._registry[key]

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, connector_type: str) -> bool:
        return (connector_type or "").lower() in cls._registry

    @classmethod
    def get_settings_schema(cls, connector_type: str) -> Type[BaseModel]:
        runtime_cls = cls.get(connector_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(
        cls,
        connector_type: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_cls = cls.get(connector_type)
        return await runtime_cls.validate_settings(settings)

    @classmethod
    def get_connection_kwargs(
        cls,
        connector_type: str,
        settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        runtime_cls = cls.get(connector_type)
        runtime = runtime_cls(**(settings or {}))
        return runtime.get_connection_kwargs()

    @classmethod
    def get_api_object(
        cls,
        connector_type: str,
        settings: dict[str, Any],
    ) -> Any:
        runtime_cls = cls.get(connector_type)
        runtime = runtime_cls(**(settings or {}))
        return runtime.get_api_object()

    @classmethod
    async def get_runtime(
        cls,
        connector_type: str,
        settings: dict[str, Any],
    ) -> BaseConnector:
        runtime_cls = cls.get(connector_type)
        validated = await runtime_cls.validate_settings(settings)
        return runtime_cls(**validated)
