"""OpenAI LLM runtime."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.llm.base import AvailableModel, BaseLLMRuntime, ModelFetchError
from giga_agent.llm.registry import LLMRegistry


@LLMRegistry.register("openai")
class OpenAIRuntime(BaseLLMRuntime):
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

    def _llm(self) -> ChatOpenAI:
        connection_kwargs = ConnectorRegistry.get_connection_kwargs(
            self.connector.type,
            self.connector.settings or {},
        )
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.id}"
            )
        settings = self._settings_payload()
        model_kwargs = {
            "temperature": settings.get("temperature"),
            "max_tokens": settings.get("max_tokens"),
            "top_p": settings.get("top_p"),
        }
        clean_model_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}
        return ChatOpenAI(
            model=self.model_id,
            **connection_kwargs,
            **clean_model_kwargs,
        )
