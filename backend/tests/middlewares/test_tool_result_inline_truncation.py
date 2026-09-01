"""ToolResultMiddleware must cap `python`/`shell` stdout even when the tool
returns its ToolMessage inside a Command (which previously bypassed processing).
"""

import types
import unittest

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from giga_agent.middlewares.tool_result import (
    ToolResultMiddleware,
    _get_max_tool_size,
)


def _request():
    runtime = types.SimpleNamespace(config={})
    return types.SimpleNamespace(
        tool_call={"name": "python", "id": "call1", "args": {}},
        runtime=runtime,
        tool=None,
    )


def _planning_request():
    runtime = types.SimpleNamespace(
        config={"configurable": {"langgraph_auth_user": {}}}
    )
    return types.SimpleNamespace(
        tool_call={"name": "present_plan", "id": "plan-call", "args": {}},
        runtime=runtime,
        tool=None,
    )


def _py_command(content: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id="call1",
                    additional_kwargs={"tool_name": "python"},
                )
            ]
        }
    )


async def _wrap(command: Command) -> Command:
    mw = ToolResultMiddleware()

    async def handler(_request):
        return command

    return await mw.wrap_tool_call(_request(), handler)


class InlineTruncationTests(unittest.IsolatedAsyncioTestCase):
    async def test_huge_python_stdout_in_command_is_truncated(self):
        huge = "Warning: merge line\n" * 50000  # ~1MB, like the gpt2-codegolf run
        out = await _wrap(_py_command(huge))
        msg = out.update["messages"][0]
        # Capped near the byte limit (+ a short hint), not the full ~1MB.
        self.assertLess(len(msg.content.encode("utf-8")), _get_max_tool_size() + 2000)
        self.assertIn("обрезан", msg.content)  # hint advises reducing output

    async def test_small_python_stdout_passes_through(self):
        out = await _wrap(_py_command("42"))
        msg = out.update["messages"][0]
        self.assertIn("42", msg.content)
        self.assertNotIn("обрезан", msg.content)

    async def test_command_preserves_planning_snapshot_and_error_status(self):
        command = Command(
            update={
                "messages": [
                    ToolMessage(
                        content="План подтверждён.",
                        tool_call_id="plan-call",
                        status="error",
                        additional_kwargs={
                            "custom_metadata": {"source": "planning"},
                            "planning": {
                                "type": "approved_plan",
                                "plan_content": "# План",
                                "todos": [],
                            },
                        },
                    )
                ]
            }
        )
        middleware = ToolResultMiddleware()

        async def handler(_request):
            return command

        out = await middleware.wrap_tool_call(_planning_request(), handler)
        message = out.update["messages"][0]
        self.assertEqual(message.status, "error")
        self.assertEqual(message.additional_kwargs["planning"]["type"], "approved_plan")
        self.assertEqual(
            message.additional_kwargs["custom_metadata"], {"source": "planning"}
        )
