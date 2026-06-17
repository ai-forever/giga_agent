"""Base runtime classes for LLM providers."""

from __future__ import annotations

import abc
import base64
from typing import Any, ClassVar, Type

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.rate_limiters import BaseRateLimiter
from pydantic import BaseModel, ConfigDict, PrivateAttr, create_model

from giga_agent.connectors.base import BaseConnector


class ModelFetchError(Exception):
    def __init__(self, llm_type: str, detail: str):
        self.llm_type = llm_type
        self.detail = detail
        super().__init__(f"Error fetching models from {llm_type}: {detail}")


class AvailableModel(BaseModel):
    id: str
    name: str | None = None
    created: int | None = None
    owned_by: str | None = None


class BaseLLMRuntime(BaseModel, abc.ABC):
    """LLM runtime contract used by routes and repositories."""

    model_config = ConfigDict(extra="allow")

    connector: BaseConnector
    model_id: str

    _runtime_fields: ClassVar[set[str]] = {
        "connector",
        "model_id",
    }
    _registered_llm_type: ClassVar[str] = ""

    _llm_instance: BaseChatModel | None = PrivateAttr(default=None)
    _rate_limiter: BaseRateLimiter | None = PrivateAttr(default=None)

    def attach_rate_limiter(self, limiter: BaseRateLimiter | None) -> None:
        """Attach a rate limiter applied on every LLM invocation."""
        self._rate_limiter = limiter
        if self._llm_instance is not None and limiter is not None:
            self._llm_instance.rate_limiter = limiter

    @classmethod
    def get_llm_type(cls) -> str:
        return cls._registered_llm_type

    @classmethod
    @abc.abstractmethod
    def supported_connector_types(cls) -> list[str]:
        raise NotImplementedError

    @classmethod
    def hidden_settings_fields(cls) -> set[str]:
        """Settings fields that must NOT be exposed on the frontend."""
        return set()

    @classmethod
    def is_connector_supported(cls, connector_type: str) -> bool:
        return (connector_type or "").lower() in {
            t.lower() for t in cls.supported_connector_types()
        }

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

    def _settings_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude=self._runtime_fields, exclude_none=True)

    async def get_llm(self) -> BaseChatModel:
        """
        Async-friendly access to the underlying LLM.

        Default implementation caches the created model inside the runtime instance.
        Providers with concurrency-sensitive initialization may override `get_llm()`
        to add their own locking.
        """
        llm = self._llm_instance
        if llm is not None:
            return llm

        llm = await self._create_llm()
        if self._rate_limiter is not None:
            # Native langchain hook: acquire is awaited before each generation.
            llm.rate_limiter = self._rate_limiter
        self._llm_instance = llm
        return llm

    @abc.abstractmethod
    async def _create_llm(self) -> BaseChatModel:
        raise NotImplementedError

    async def check_connection(self) -> None:
        llm = await self.get_llm()
        await llm.ainvoke("ping")

    def can_analyze_image(self) -> bool:
        return True

    async def analyze_image(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpg",
    ) -> str:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{mime_type};base64,{image_b64}"
        llm = await self.get_llm()
        llm = llm.with_config(tags=["nostream"])
        response = await llm.ainvoke(
            [
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                )
            ]
        )
        return response.text

    @classmethod
    @abc.abstractmethod
    async def fetch_available_models(
        cls,
        *,
        connector: BaseConnector,
    ) -> list[AvailableModel]:
        raise NotImplementedError
