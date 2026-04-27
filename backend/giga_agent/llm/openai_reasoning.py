"""ChatOpenAI subclass that preserves provider reasoning_content for round-trips.

Some OpenAI-compatible providers (e.g. DeepSeek in thinking mode) return a
``reasoning_content`` field alongside the standard ``content`` in assistant
messages and require that field to be echoed back in subsequent
requests.  The stock ``langchain_openai.ChatOpenAI`` explicitly does not
handle provider-specific extras, so this thin subclass fills the gap:

* ``_create_chat_result`` – after the base conversion, picks ``reasoning_content``
  from the raw response dict and stores it in ``AIMessage.additional_kwargs``.
* ``_get_request_payload`` – after the base serialisation, re-injects
  ``reasoning_content`` into the assistant message dicts so the provider
  accepts the follow-up call.

Nothing in this module touches the public chat UI, export helpers, or logs.
"""

from __future__ import annotations

from typing import Any

import openai
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


class ChatOpenAIReasoning(ChatOpenAI):
    """``ChatOpenAI`` that survives ``reasoning_content`` round-trips."""

    # ------------------------------------------------------------------
    # Capture reasoning_content from the raw response
    # ------------------------------------------------------------------

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ):
        result = super()._create_chat_result(response, generation_info)

        response_dict: dict[str, Any] = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )

        choices = response_dict.get("choices") or []
        for i, choice in enumerate(choices):
            reasoning = (choice.get("message") or {}).get("reasoning_content")
            if not reasoning:
                continue
            if i < len(result.generations):
                msg = result.generations[i].message
                if isinstance(msg, AIMessage):
                    msg.additional_kwargs["reasoning_content"] = reasoning

        return result

    # ------------------------------------------------------------------
    # Re-inject reasoning_content when building the next request payload
    # ------------------------------------------------------------------

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

        # Walk the converted payload messages in order; each "assistant" dict
        # corresponds to the next AIMessage in the original sequence.
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
