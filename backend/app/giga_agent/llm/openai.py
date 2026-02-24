"""OpenAI LLM runtime."""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from giga_agent.connectors.base import BaseConnector
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
        connector: BaseConnector,
    ) -> list[AvailableModel]:
        kwargs = connector.get_connection_kwargs()
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
        connection_kwargs = self.connector.get_connection_kwargs()
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.__class__.__name__}"
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
