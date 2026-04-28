"""DeepSeek LLM runtime."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek
from openai import AsyncOpenAI

from giga_agent.connectors.base import BaseConnector
from giga_agent.llm.base import AvailableModel, BaseLLMRuntime, ModelFetchError
from giga_agent.llm.registry import LLMRegistry


class _ChatDeepSeekWithReplay(ChatDeepSeek):
    """ChatDeepSeek that replays reasoning_content in follow-up requests.

    ``ChatDeepSeek`` (v1.0.1) already captures ``reasoning_content`` from
    responses into ``AIMessage.additional_kwargs``.  This subclass adds the
    missing half: re-injecting that field into the assistant message dict on
    every subsequent API call, which DeepSeek's thinking-mode API requires.
    """

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        if "messages" not in payload:
            return payload

        ai_iter = (m for m in messages if isinstance(m, AIMessage))
        for msg_dict in payload["messages"]:
            if msg_dict.get("role") != "assistant":
                continue
            ai_msg = next(ai_iter, None)
            if ai_msg is None:
                break
            reasoning = ai_msg.additional_kwargs.get("reasoning_content")
            if reasoning:
                msg_dict["reasoning_content"] = reasoning

        return payload


@LLMRegistry.register("deepseek")
class DeepSeekRuntime(BaseLLMRuntime):
    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["deepseek"]

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
            client = AsyncOpenAI(
                **kwargs,
                timeout=30.0,
            )
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
            raise ModelFetchError("deepseek", str(e)) from e

    async def _create_llm(self) -> _ChatDeepSeekWithReplay:
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
        chat_kwargs = {
            "api_key": connection_kwargs["api_key"],
            "api_base": connection_kwargs["base_url"],
        }
        return _ChatDeepSeekWithReplay(
            model=self.model_id,
            **chat_kwargs,
            **clean_model_kwargs,
        )
