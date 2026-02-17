"""OpenAI LLM runtime."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from giga_agent.llm.base import AvailableModel, BaseLLM, ModelFetchError
from giga_agent.llm.registry import LLMRegistry


@LLMRegistry.register("openai")
class OpenAILLM(BaseLLM):
    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["openai"]

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector_type: str,
        connector_settings: dict[str, Any],
    ) -> list[AvailableModel]:
        kwargs = cls._get_connection_kwargs(
            connector_type=connector_type,
            connector_settings=connector_settings,
        )
        if not kwargs:
            return []

        try:
            client = AsyncOpenAI(**kwargs, timeout=30.0)
            response = await client.models.list()
            models = [
                AvailableModel(
                    id=model.id,
                    name=model.id,
                    created=model.created,
                    owned_by=model.owned_by,
                )
                for model in response.data
            ]
            models.sort(key=lambda item: item.id)
            return models
        except Exception as e:
            raise ModelFetchError("openai", str(e)) from e

    @classmethod
    def build_chat_model_from_kwargs(
        cls,
        *,
        model_id: str,
        connection_kwargs: dict[str, Any],
        llm_settings: dict[str, Any] | None = None,
    ) -> ChatOpenAI:
        settings = llm_settings or {}
        model_kwargs = {
            "temperature": settings.get("temperature"),
            "max_tokens": settings.get("max_tokens"),
            "top_p": settings.get("top_p"),
        }
        clean_model_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}
        return ChatOpenAI(model=model_id, **connection_kwargs, **clean_model_kwargs)
