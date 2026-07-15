"""Tests for the DeepSeek connector and LLM runtime."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import giga_agent.connectors  # noqa: F401 – triggers registry population
import giga_agent.llm  # noqa: F401 – triggers registry population
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from giga_agent.connectors.deepseek import DEEPSEEK_DEFAULT_BASE_URL, DeepSeekConnector
from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.llm.deepseek import DeepSeekRuntime, _ChatDeepSeekWithReplay
from giga_agent.llm.registry import LLMRegistry


# ---------------------------------------------------------------------------
# Connector tests
# ---------------------------------------------------------------------------


class DeepSeekConnectorRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_deepseek_registered(self):
        self.assertIn("deepseek", ConnectorRegistry.available_types())

    async def test_validate_requires_key_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                await ConnectorRegistry.validate_settings("deepseek", {})

    async def test_validate_accepts_env_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}, clear=True):
            settings = await ConnectorRegistry.validate_settings("deepseek", {})
        self.assertNotIn("api_key", settings)
        self.assertEqual(settings["base_url"], DEEPSEEK_DEFAULT_BASE_URL)

    def test_connection_kwargs_returns_api_key(self):
        connector = DeepSeekConnector(api_key="sk-ds-test")
        kwargs = connector.get_connection_kwargs()
        self.assertEqual(
            kwargs,
            {"api_key": "sk-ds-test", "base_url": DEEPSEEK_DEFAULT_BASE_URL},
        )

    def test_connection_kwargs_none_when_no_key(self):
        connector = DeepSeekConnector()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(connector.get_connection_kwargs())

    async def test_check_connection_calls_models_list(self):
        connector = DeepSeekConnector(
            api_key="sk-ds-test",
            base_url="https://deepseek.example",
        )
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=[])
        with patch(
            "giga_agent.connectors.deepseek.AsyncOpenAI",
            return_value=mock_client,
        ) as mocked:
            result = await connector.check_connection()

        self.assertTrue(result)
        mocked.assert_called_once_with(
            api_key="sk-ds-test",
            base_url="https://deepseek.example",
            timeout=30.0,
        )
        mock_client.models.list.assert_awaited_once()


# ---------------------------------------------------------------------------
# LLM runtime tests
# ---------------------------------------------------------------------------


class DeepSeekRuntimeRegistryTests(unittest.TestCase):
    def test_deepseek_runtime_registered(self):
        self.assertIn("deepseek", LLMRegistry.available_types())

    def test_supported_connector_types(self):
        self.assertEqual(DeepSeekRuntime.supported_connector_types(), ["deepseek"])


# ---------------------------------------------------------------------------
# _ChatDeepSeekWithReplay tests
# ---------------------------------------------------------------------------


class _MessagesWrapper:
    def __init__(self, msgs):
        self._msgs = msgs

    def to_messages(self):
        return self._msgs


def _make_chat_result(content: str) -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class ChatDeepSeekWithReplayTests(unittest.TestCase):
    """The _get_request_payload override replays reasoning_content."""

    def _run_payload(self, messages: list, base_payload: dict) -> dict:
        instance = _ChatDeepSeekWithReplay.__new__(_ChatDeepSeekWithReplay)
        wrapper = _MessagesWrapper(messages)
        with (
            patch.object(
                _ChatDeepSeekWithReplay.__bases__[0],
                "_get_request_payload",
                return_value=base_payload,
            ),
            patch.object(
                _ChatDeepSeekWithReplay,
                "_convert_input",
                return_value=wrapper,
            ),
        ):
            return _ChatDeepSeekWithReplay._get_request_payload(instance, messages)

    def test_reasoning_content_injected(self):
        ai_msg = AIMessage(
            content="Answer",
            additional_kwargs={"reasoning_content": "Thinking..."},
        )
        messages = [HumanMessage(content="Q"), ai_msg]
        base_payload = {
            "messages": [
                {"role": "user", "content": "Q"},
                {"role": "assistant", "content": "Answer"},
            ]
        }

        payload = self._run_payload(messages, base_payload)
        assistant = next(d for d in payload["messages"] if d["role"] == "assistant")
        self.assertEqual(assistant.get("reasoning_content"), "Thinking...")

    def test_no_reasoning_content_set_to_empty(self):
        # Assistant messages without reasoning (e.g. few-shot examples) get an
        # explicit empty reasoning_content so the API accepts the follow-up.
        ai_msg = AIMessage(content="Plain answer.")
        messages = [HumanMessage(content="Q"), ai_msg]
        base_payload = {
            "messages": [
                {"role": "user", "content": "Q"},
                {"role": "assistant", "content": "Plain answer."},
            ]
        }

        payload = self._run_payload(messages, base_payload)
        assistant = next(d for d in payload["messages"] if d["role"] == "assistant")
        self.assertEqual(assistant.get("reasoning_content"), "")

    def test_tool_call_loop_scenario(self):
        """model (with reasoning) → tool → second model call preserves reasoning."""
        ai_with_tools = AIMessage(
            content="",
            tool_calls=[
                {"name": "shell", "args": {"cmd": "python tsp.py"}, "id": "c1"}
            ],
            additional_kwargs={"reasoning_content": "I should run a script"},
        )
        tool_result = ToolMessage(content="Done", tool_call_id="c1")
        messages = [HumanMessage(content="Visualise TSP"), ai_with_tools, tool_result]

        base_payload = {
            "messages": [
                {"role": "user", "content": "Visualise TSP"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "shell",
                                "arguments": '{"cmd":"python tsp.py"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "Done"},
            ]
        }

        payload = self._run_payload(messages, base_payload)
        assistant = next(d for d in payload["messages"] if d["role"] == "assistant")
        self.assertEqual(assistant.get("reasoning_content"), "I should run a script")
