"""Registry for channel runtime classes."""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel

from giga_agent.channels.base import Channel, ChannelInstanceMetadata
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class ChannelRegistry:
    _registry: dict[str, Type[Channel]] = {}

    @classmethod
    def register(cls, channel_type: str):
        def decorator(channel_cls: Type[Channel]) -> Type[Channel]:
            key = (channel_type or "").lower()
            if key in cls._registry:
                logger.warning(
                    "Channel runtime '%s' is already registered (%s), overriding with %s",
                    key,
                    cls._registry[key].__name__,
                    channel_cls.__name__,
                )
            cls._registry[key] = channel_cls
            return channel_cls

        return decorator

    @classmethod
    def get(cls, channel_type: str) -> Type[Channel]:
        key = (channel_type or "").lower()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown channel type: '{channel_type}'. Available: {cls.available_types()}"
            )
        return cls._registry[key]

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def is_registered(cls, channel_type: str) -> bool:
        return (channel_type or "").lower() in cls._registry

    @classmethod
    def get_settings_schema(cls, channel_type: str) -> Type[BaseModel]:
        runtime_cls = cls.get(channel_type)
        return runtime_cls.settings_schema()

    @classmethod
    async def validate_settings(
        cls,
        channel_type: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_cls = cls.get(channel_type)
        return await runtime_cls.validate_settings(settings)

    @classmethod
    async def get_runtime(
        cls,
        channel_type: str,
        settings: dict[str, Any],
    ) -> Channel:
        runtime_cls = cls.get(channel_type)
        validated = await runtime_cls.validate_settings(settings)
        return runtime_cls(**validated)

    @classmethod
    async def resolve_instance_metadata(
        cls,
        channel_type: str,
        settings: dict[str, Any],
    ) -> ChannelInstanceMetadata:
        runtime = await cls.get_runtime(channel_type, settings)
        return await runtime.resolve_instance_metadata()
