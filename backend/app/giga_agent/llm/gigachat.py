"""GigaChat LLM runtime."""

from __future__ import annotations

from typing import Any

from langchain_gigachat import GigaChat

from giga_agent.llm.base import AvailableModel, BaseLLM, ModelFetchError
from giga_agent.llm.registry import LLMRegistry


@LLMRegistry.register("gigachat")
class GigaChatLLM(BaseLLM):
    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

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
        if kwargs is None:
            return []

        try:
            llm = GigaChat(**kwargs)
            return [
                AvailableModel(
                    id=model.id_,
                    name=model.id_,
                    owned_by=model.owned_by,
                )
                for model in (await llm.aget_models()).data
            ]
        except Exception as e:
            raise ModelFetchError("gigachat", str(e)) from e

    @classmethod
    def build_chat_model_from_kwargs(
        cls,
        *,
        model_id: str,
        connection_kwargs: dict[str, Any],
        llm_settings: dict[str, Any] | None = None,
    ) -> GigaChat:
        settings = llm_settings or {}
        model_kwargs = {
            "temperature": settings.get("temperature"),
            "max_tokens": settings.get("max_tokens"),
            "top_p": settings.get("top_p"),
        }
        clean_model_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}
        return GigaChat(model=model_id, **connection_kwargs, **clean_model_kwargs)
