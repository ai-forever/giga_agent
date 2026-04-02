"""Base runtime contract for messenger channels."""

from __future__ import annotations

import abc
from typing import Any, ClassVar, Type

from pydantic import BaseModel, ConfigDict, create_model

from giga_agent.models.channel import ChannelBot


class ChannelInstanceMetadata(BaseModel):
    """Metadata that a channel runtime can resolve for a stored instance."""

    bot_username: str | None = None


class Channel(BaseModel, abc.ABC):
    """Base channel runtime used for settings validation and lifecycle hooks."""

    model_config = ConfigDict(extra="forbid")

    channel_type: ClassVar[str]
    _runtime_fields: ClassVar[set[str]] = set()

    @classmethod
    def type(cls) -> str:
        key = (getattr(cls, "channel_type", "") or "").lower()
        if not key:
            raise ValueError(f"{cls.__name__} must define channel_type")
        return key

    @classmethod
    def hidden_settings_fields(cls) -> set[str]:
        return set()

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        fields: dict[str, tuple[Any, Any]] = {}
        excluded = cls._runtime_fields | cls.hidden_settings_fields()

        for name, field_info in cls.model_fields.items():
            if name in excluded:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)

    async def resolve_instance_metadata(self) -> ChannelInstanceMetadata:
        return ChannelInstanceMetadata()

    @abc.abstractmethod
    async def start(self, bot: ChannelBot) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def stop(self, bot: ChannelBot) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def restart(self, bot: ChannelBot) -> None:
        raise NotImplementedError
