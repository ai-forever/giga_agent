"""Base runtime class for external service connectors."""

from __future__ import annotations

import abc
from typing import Any, ClassVar, Type

from pydantic import BaseModel, ConfigDict, create_model


class BaseConnector(BaseModel, abc.ABC):
    """Base connector runtime used for settings validation and connection kwargs."""

    model_config = ConfigDict(extra="forbid")

    _runtime_fields: ClassVar[set[str]] = set()

    @classmethod
    def settings_schema(cls) -> Type[BaseModel]:
        fields: dict[str, tuple[Any, Any]] = {}
        for name, field_info in cls.model_fields.items():
            if name in cls._runtime_fields:
                continue
            fields[name] = (field_info.annotation, field_info)

        return create_model(f"{cls.__name__}Settings", **fields)

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        schema = cls.settings_schema()
        return schema(**settings).model_dump(exclude_none=True)

    @classmethod
    @abc.abstractmethod
    def get_connection_kwargs(cls, settings: dict[str, Any]) -> dict[str, Any] | None:
        """Build normalized kwargs for downstream clients from connector settings."""
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def get_api_object(cls, settings: dict[str, Any]) -> Any:
        """Build provider API object from connector settings."""
        raise NotImplementedError
