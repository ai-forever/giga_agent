"""Regression tests for ChatOpenAIReasoning.

Verifies that:
1.  ``reasoning_content`` returned by a provider is captured into
    ``AIMessage.additional_kwargs``.
2.  That field is replayed in the *next* API payload (simulating a tool-call
    loop where the graph calls the model a second time).
3.  Regular models that return no ``reasoning_content`` are unaffected.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from giga_agent.llm.openai_reasoning import ChatOpenAIReasoning


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_result(content: str) -> ChatResult:
    return ChatResult(
        generations=[ChatGeneration(message=AIMessage(content=content))]
    )


def _fake_openai_response(content: str, reasoning: str | None = None) -> MagicMock:
    """Return a minimal fake ``openai.BaseModel``-like response."""
    message_data: dict = {
        "role": "assistant",
        "content": content,
    }
    if reasoning:
        message_data["reasoning_content"] = reasoning

    choice = {"message": message_data, "finish_reason": "stop"}
    response = MagicMock()
    response.model_dump.return_value = {
        "choices": [choice],
        "usage": None,
        "model": "deepseek-reasoner",
    }
    # Make response.choices accessible for the hasattr checks in the base class.
    response.choices = [
        types.SimpleNamespace(
            message=types.SimpleNamespace(
                content=content,
                **{"reasoning_content": reasoning} if reasoning else {},
            )
        )
    ]
    return response


class _MessagesWrapper:
    """Minimal stand-in for the object returned by ``_convert_input``."""

    def __init__(self, msgs):
        self._msgs = msgs

    def to_messages(self):
        return self._msgs


# ---------------------------------------------------------------------------
# Capture tests
# ---------------------------------------------------------------------------


class ChatOpenAIReasoningCaptureTests(unittest.TestCase):
    """``_create_chat_result`` stores reasoning_content in additional_kwargs."""

    def test_reasoning_content_stored_in_additional_kwargs(self):
        fake_resp = _fake_openai_response(
            content="Here is the answer.",
            reasoning="I need to think carefully...",
        )

        base_result = _make_chat_result("Here is the answer.")
        with patch.object(
            ChatOpenAIReasoning.__bases__[0],
            "_create_chat_result",
            return_value=base_result,
        ):
            instance = ChatOpenAIReasoning.__new__(ChatOpenAIReasoning)
            result = ChatOpenAIReasoning._create_chat_result(instance, fake_resp)

        msg = result.generations[0].message
        self.assertIsInstance(msg, AIMessage)
        self.assertEqual(
            msg.additional_kwargs.get("reasoning_content"),
            "I need to think carefully...",
        )

    def test_no_reasoning_content_unaffected(self):
        fake_resp = _fake_openai_response(content="Normal answer.")

        base_result = _make_chat_result("Normal answer.")
        with patch.object(
            ChatOpenAIReasoning.__bases__[0],
            "_create_chat_result",
            return_value=base_result,
        ):
            instance = ChatOpenAIReasoning.__new__(ChatOpenAIReasoning)
            result = ChatOpenAIReasoning._create_chat_result(instance, fake_resp)

        msg = result.generations[0].message
        self.assertIsInstance(msg, AIMessage)
        self.assertNotIn("reasoning_content", msg.additional_kwargs)


# ---------------------------------------------------------------------------
# Replay tests
# ---------------------------------------------------------------------------


class ChatOpenAIReasoningReplayTests(unittest.TestCase):
    """``_get_request_payload`` re-injects reasoning_content into payload."""

    def _run_payload(
        self, messages: list, base_payload: dict
    ) -> dict:
        """Call ``_get_request_payload`` with the two relevant methods patched."""
        instance = ChatOpenAIReasoning.__new__(ChatOpenAIReasoning)
        wrapper = _MessagesWrapper(messages)

        with patch.object(
            ChatOpenAIReasoning.__bases__[0],
            "_get_request_payload",
            return_value=base_payload,
        ), patch.object(
            ChatOpenAIReasoning,
            "_convert_input",
            return_value=wrapper,
        ):
            return ChatOpenAIReasoning._get_request_payload(instance, messages)

    def test_reasoning_content_injected_into_assistant_dict(self):
        ai_msg = AIMessage(
            content="I solved it.",
            additional_kwargs={"reasoning_content": "Step by step thinking..."},
        )
        messages = [HumanMessage(content="Solve X"), ai_msg]

        base_payload = {
            "messages": [
                {"role": "user", "content": "Solve X"},
                {"role": "assistant", "content": "I solved it."},
            ],
            "model": "deepseek-reasoner",
        }

        payload = self._run_payload(messages, base_payload)

        assistant_dict = next(
            d for d in payload["messages"] if d["role"] == "assistant"
        )
        self.assertEqual(
            assistant_dict.get("reasoning_content"), "Step by step thinking..."
        )

    def test_no_reasoning_content_not_added(self):
        ai_msg = AIMessage(content="Plain answer.")
        messages = [HumanMessage(content="Question"), ai_msg]

        base_payload = {
            "messages": [
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Plain answer."},
            ],
        }

        payload = self._run_payload(messages, base_payload)

        assistant_dict = next(
            d for d in payload["messages"] if d["role"] == "assistant"
        )
        self.assertNotIn("reasoning_content", assistant_dict)

    def test_tool_call_loop_reasoning_preserved(self):
        """Simulate the exact failure: model (with reasoning) → tool call → model again."""
        ai_msg_with_tool = AIMessage(
            content="",
            tool_calls=[
                {"name": "shell", "args": {"cmd": "python tsp.py"}, "id": "call_1"}
            ],
            additional_kwargs={"reasoning_content": "I should run a script..."},
        )
        tool_result = ToolMessage(content="Done", tool_call_id="call_1")
        messages = [
            HumanMessage(content="Visualise TSP"),
            ai_msg_with_tool,
            tool_result,
        ]

        base_payload = {
            "messages": [
                {"role": "user", "content": "Visualise TSP"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "shell", "arguments": '{"cmd":"python tsp.py"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "Done"},
            ],
        }

        payload = self._run_payload(messages, base_payload)

        assistant_dict = next(
            d for d in payload["messages"] if d["role"] == "assistant"
        )
        self.assertEqual(
            assistant_dict.get("reasoning_content"), "I should run a script..."
        )
