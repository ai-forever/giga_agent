import types
import unittest

from giga_agent.modules.subagents.tools import _tool_result


class SubagentToolWidgetPayloadTests(unittest.TestCase):
    def test_activity_task_is_preserved_for_all_terminal_and_waiting_states(self):
        runtime = types.SimpleNamespace(tool_call_id="subtask-call")

        for status in ("running", "interrupted", "completed", "error"):
            with self.subTest(status=status):
                snapshot = {
                    "agent_id": "builtin:subagents:researcher",
                    "agent_name": "Researcher",
                    "task": "Find the relevant implementation details",
                    "child_thread_id": "child-thread",
                    "status": status,
                }

                command = _tool_result(
                    runtime,
                    content="result",
                    snapshot=snapshot,
                    is_error=status == "error",
                )

                message = command.update["messages"][0]
                self.assertEqual(
                    message.additional_kwargs["subagent_activity"]["task"],
                    "Find the relevant implementation details",
                )
                self.assertEqual(
                    message.status, "error" if status == "error" else "success"
                )
