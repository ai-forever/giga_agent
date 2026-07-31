"""Tests for planning and interrupt forwarding in the experimental wrapper."""

from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from giga_agent.agents.experimental import graph as experimental_graph


def _client_session(client):
    @asynccontextmanager
    async def session(_config):
        yield client

    return session


def _client():
    return SimpleNamespace(
        threads=SimpleNamespace(
            create=AsyncMock(return_value={"thread_id": "inner-thread"}),
            get_state=AsyncMock(),
        ),
        runs=SimpleNamespace(
            create=AsyncMock(return_value={"run_id": "inner-run"}),
            get=AsyncMock(),
        ),
    )


def _planning_messages(snapshot_type: str, tool_name: str):
    tool_call_id = f"{tool_name}-call"
    planning = {"type": snapshot_type, "todos": []}
    if snapshot_type in {"approved_plan", "rejected_plan"}:
        planning["plan_content"] = "# План"
    return [
        {
            "type": "ai",
            "id": f"{tool_name}-ai",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "name": tool_name,
                    "args": {},
                    "type": "tool_call",
                }
            ],
        },
        {
            "type": "tool",
            "id": f"{tool_name}-result",
            "content": "result",
            "tool_call_id": tool_call_id,
            "status": "success",
            "additional_kwargs": {"planning": planning},
        },
    ]


class PlanningWidgetHelperTests(unittest.TestCase):
    def test_only_persisted_planning_snapshots_are_widgets(self):
        for snapshot_type in (
            "approved_plan",
            "rejected_plan",
            "todo_error",
            "todo_snapshot",
        ):
            with self.subTest(snapshot_type=snapshot_type):
                self.assertTrue(
                    experimental_graph._is_widget_tool(
                        {"additional_kwargs": {"planning": {"type": snapshot_type}}}
                    )
                )

        self.assertFalse(
            experimental_graph._is_widget_tool(
                {"additional_kwargs": {"planning": {"type": "draft_plan"}}}
            )
        )
        self.assertFalse(experimental_graph._is_widget_tool({}))

    def test_forward_widget_restores_original_planning_tool_name(self):
        for snapshot_type, tool_name in (
            ("approved_plan", "present_plan"),
            ("rejected_plan", "present_plan"),
            ("todo_snapshot", "write_todo"),
            ("todo_error", "write_todo"),
        ):
            with self.subTest(snapshot_type=snapshot_type):
                messages = _planning_messages(snapshot_type, tool_name)
                stub, result = experimental_graph._forward_widget(
                    messages[-1], messages
                )
                tool_call_id = f"{tool_name}-call"

                self.assertEqual(stub.id, f"exp-toolstub-{tool_call_id}")
                self.assertEqual(stub.tool_calls[0]["name"], tool_name)
                self.assertEqual(result.id, f"exp-toolmsg-{tool_call_id}")
                self.assertEqual(result.tool_call_id, tool_call_id)
                self.assertEqual(result.name, tool_name)
                self.assertEqual(
                    result.additional_kwargs["planning"]["type"], snapshot_type
                )

    def test_planning_state_update_selects_only_ui_fields(self):
        self.assertEqual(
            experimental_graph._planning_state_update(
                {
                    "mode": "plan",
                    "plan_approved": False,
                    "todos": [{"id": "1"}],
                    "plan_content": "not mirrored",
                    "messages": [],
                }
            ),
            {
                "mode": "plan",
                "plan_approved": False,
                "todos": [{"id": "1"}],
            },
        )

    def test_plan_interrupt_gets_present_plan_tool_call_id(self):
        messages = _planning_messages("approved_plan", "present_plan")[:1]
        prepared = experimental_graph._prepare_interrupt_value(
            {
                "type": "plan_approval",
                "plan_content": "# План",
                "todos": [],
            },
            messages,
        )

        self.assertEqual(prepared["tool_call_id"], "present_plan-call")

    def test_plan_approval_messages_match_forwarded_widget_ids(self):
        interrupt_value = {
            "type": "plan_approval",
            "tool_call_id": "present-plan-call",
            "plan_content": "# План",
            "todos": [{"id": "1"}],
        }
        stub, result = experimental_graph._plan_approval_messages(
            interrupt_value, {"action": "approve"}
        )

        self.assertEqual(stub.id, "exp-toolstub-present-plan-call")
        self.assertEqual(result.id, "exp-toolmsg-present-plan-call")
        self.assertEqual(result.tool_call_id, "present-plan-call")
        self.assertEqual(
            result.additional_kwargs["planning"],
            {
                "type": "approved_plan",
                "plan_content": "# План",
                "todos": [{"id": "1"}],
            },
        )

    def test_plan_rejection_messages_preserve_plan_content(self):
        interrupt_value = {
            "type": "plan_approval",
            "tool_call_id": "present-plan-call",
            "plan_content": "# План",
            "todos": [{"id": "1"}],
        }
        stub, result = experimental_graph._plan_approval_messages(
            interrupt_value,
            {"action": "reject", "feedback": "Нужно доработать"},
        )

        self.assertEqual(stub.id, "exp-toolstub-present-plan-call")
        self.assertEqual(result.id, "exp-toolmsg-present-plan-call")
        self.assertEqual(result.content, "План отменён.")
        self.assertEqual(
            result.additional_kwargs["planning"],
            {
                "type": "rejected_plan",
                "plan_content": "# План",
                "todos": [{"id": "1"}],
            },
        )


class ExperimentalGraphAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_kickoff_forwards_plan_mode_from_chat_config(self):
        client = _client()
        config = {
            "configurable": {
                "plan_mode": True,
                "deep_research_forced": True,
                "selected_skills": ["review"],
                "thread_id": "outer-thread",
            }
        }

        with (
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph,
                "resolve_project_id",
                AsyncMock(return_value=None),
            ),
            patch.object(experimental_graph, "push_ui_message"),
            patch.object(experimental_graph, "_outer_thread_id", return_value=None),
        ):
            update = await experimental_graph.kickoff(
                {"messages": [HumanMessage("Составь план")]}, config
            )

        inner_config = client.runs.create.await_args.kwargs["config"]["configurable"]
        self.assertEqual(
            inner_config,
            {
                "auto_approve": True,
                "experimental_inner": True,
                "deep_research_forced": True,
                "plan_mode": True,
                "selected_skills": ["review"],
            },
        )
        self.assertNotIn("inner_configurable", update)

    async def test_pump_forwards_todo_widget_and_planning_state(self):
        client = _client()
        messages = _planning_messages("todo_snapshot", "write_todo")
        client.threads.get_state.return_value = {
            "values": {
                "messages": messages,
                "mode": "normal",
                "plan_approved": True,
                "todos": [{"id": "1", "content": "A", "status": "pending"}],
            }
        }

        with (
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_consume_live", AsyncMock(return_value=None)
            ),
            patch.object(
                experimental_graph,
                "_sync_title_from_inner",
                AsyncMock(return_value=True),
            ),
        ):
            update = await experimental_graph.pump(
                {
                    "inner_thread_id": "inner-thread",
                    "inner_run_id": "inner-run",
                    "processed_inner_ids": [],
                },
                {},
            )

        stub, result = update["messages"]
        self.assertEqual(stub.tool_calls[0]["name"], "write_todo")
        self.assertEqual(result.content, "result")
        self.assertEqual(update["mode"], "normal")
        self.assertTrue(update["plan_approved"])
        self.assertEqual(update["todos"][0]["id"], "1")

    async def test_pump_exposes_arbitrary_inner_interrupt_and_state(self):
        client = _client()
        snapshot = {
            "values": {
                "messages": [],
                "mode": "plan",
                "plan_approved": False,
                "todos": [{"id": "1"}],
            },
            "interrupts": [{"value": {"type": "custom_hitl", "opaque": 7}}],
        }
        client.threads.get_state.return_value = snapshot
        client.runs.get.return_value = {"status": "interrupted"}

        with (
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_consume_live", AsyncMock(return_value=None)
            ),
            patch.object(
                experimental_graph,
                "_sync_title_from_inner",
                AsyncMock(return_value=True),
            ),
        ):
            update = await experimental_graph.pump(
                {
                    "inner_thread_id": "inner-thread",
                    "inner_run_id": "inner-run",
                    "processed_inner_ids": [],
                },
                {},
            )

        self.assertEqual(
            update["interrupt_value"], {"type": "custom_hitl", "opaque": 7}
        )
        self.assertEqual(update["mode"], "plan")
        self.assertEqual(update["todos"], [{"id": "1"}])

    async def test_pump_enriches_plan_interrupt_with_tool_call_id(self):
        client = _client()
        messages = _planning_messages("approved_plan", "present_plan")[:1]
        snapshot = {
            "values": {
                "messages": messages,
                "mode": "plan",
                "plan_approved": False,
                "todos": [{"id": "1"}],
            },
            "interrupts": [
                {
                    "value": {
                        "type": "plan_approval",
                        "plan_content": "# План",
                        "todos": [{"id": "1"}],
                    }
                }
            ],
        }
        client.threads.get_state.return_value = snapshot
        client.runs.get.return_value = {"status": "interrupted"}

        with (
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_consume_live", AsyncMock(return_value=None)
            ),
            patch.object(
                experimental_graph,
                "_sync_title_from_inner",
                AsyncMock(return_value=True),
            ),
        ):
            update = await experimental_graph.pump(
                {
                    "inner_thread_id": "inner-thread",
                    "inner_run_id": "inner-run",
                    "processed_inner_ids": [],
                },
                {},
            )

        self.assertEqual(update["interrupt_value"]["tool_call_id"], "present_plan-call")

    async def test_interrupt_node_commits_approved_plan_immediately(self):
        client = _client()
        payload = {
            "type": "plan_approval",
            "tool_call_id": "present-plan-call",
            "plan_content": "# План",
            "todos": [{"id": "1"}],
        }
        state = {
            "messages": [],
            "inner_thread_id": "inner-thread",
            "inner_run_id": "old-run",
            "interrupt_value": payload,
        }

        with (
            patch.object(
                experimental_graph,
                "interrupt",
                return_value={"action": "approve"},
            ),
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_forget_statuses", AsyncMock(return_value=None)
            ),
        ):
            update = await experimental_graph.interrupt_node(state, {})

        stub, result = update["messages"]
        self.assertEqual(stub.id, "exp-toolstub-present-plan-call")
        self.assertEqual(result.id, "exp-toolmsg-present-plan-call")
        self.assertEqual(result.additional_kwargs["planning"]["type"], "approved_plan")
        self.assertEqual(update["mode"], "normal")
        self.assertTrue(update["plan_approved"])
        self.assertEqual(update["todos"], [{"id": "1"}])

    async def test_interrupt_node_commits_rejected_plan_immediately(self):
        client = _client()
        payload = {
            "type": "plan_approval",
            "tool_call_id": "present-plan-call",
            "plan_content": "# План",
            "todos": [{"id": "1"}],
        }
        state = {
            "messages": [],
            "inner_thread_id": "inner-thread",
            "inner_run_id": "old-run",
            "interrupt_value": payload,
        }

        with (
            patch.object(
                experimental_graph,
                "interrupt",
                return_value={"action": "reject", "feedback": "Переделай"},
            ),
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_forget_statuses", AsyncMock(return_value=None)
            ),
        ):
            update = await experimental_graph.interrupt_node(state, {})

        _, result = update["messages"]
        self.assertEqual(result.additional_kwargs["planning"]["type"], "rejected_plan")
        self.assertEqual(result.additional_kwargs["planning"]["plan_content"], "# План")
        self.assertEqual(update["mode"], "plan")
        self.assertFalse(update["plan_approved"])

    async def test_interrupt_node_uses_current_chat_config(self):
        client = _client()
        payload = {"type": "custom_hitl", "opaque": 7}
        answer = {"decision": "continue", "value": 9}
        state = {
            "messages": [],
            "inner_thread_id": "inner-thread",
            "inner_run_id": "old-run",
            "interrupt_value": payload,
        }
        config = {
            "configurable": {
                "plan_mode": True,
                "selected_skills": ["review"],
            }
        }

        with (
            patch.object(experimental_graph, "interrupt", return_value=answer),
            patch.object(experimental_graph, "client_session", _client_session(client)),
            patch.object(
                experimental_graph, "_forget_statuses", AsyncMock(return_value=None)
            ),
        ):
            update = await experimental_graph.interrupt_node(state, config)

        kwargs = client.runs.create.await_args.kwargs
        self.assertEqual(kwargs["command"], {"resume": answer})
        self.assertEqual(
            kwargs["config"]["configurable"],
            {
                "plan_mode": True,
                "selected_skills": ["review"],
                "auto_approve": True,
                "experimental_inner": True,
            },
        )
        self.assertEqual(update["messages"], [])
        self.assertEqual(update["interrupt_value"], None)


if __name__ == "__main__":
    unittest.main()
