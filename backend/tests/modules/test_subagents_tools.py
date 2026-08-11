import asyncio
import json
import types
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from giga_agent.modules.subagents.module import SubagentsModule
from giga_agent.modules.subagents_legacy.runtime import invoke_subgraph_cli
from giga_agent.modules.subagents.tools import (
    _last_final_ai_message,
    _result_from_thread_state,
    _tool_result,
    _validate_thread_for_result,
    _validate_subagent_thread,
    subtask,
    thread_result,
)


class SubagentCliContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuation_uses_stable_checkpoint_namespace(self):
        graph = types.SimpleNamespace(ainvoke=AsyncMock(return_value={}))
        runtime = types.SimpleNamespace(
            config={
                "configurable": {
                    "thread_id": "parent-thread",
                    "checkpoint_ns": "tools:parent-call",
                    "checkpoint_id": "parent-checkpoint",
                    "checkpoint_map": {"": "parent-checkpoint"},
                    "project_id": "project-1",
                }
            }
        )

        await invoke_subgraph_cli(
            graph,
            {"messages": []},
            runtime,
            thread_id="child-thread",
        )

        config = graph.ainvoke.await_args.args[1]["configurable"]
        self.assertEqual(config["thread_id"], "child-thread")
        self.assertEqual(config["checkpoint_ns"], "")
        self.assertEqual(config["project_id"], "project-1")
        self.assertNotIn("checkpoint_id", config)
        self.assertNotIn("checkpoint_map", config)


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


class SubagentThreadResultTests(unittest.TestCase):
    def test_last_final_ai_message_skips_tool_calls_and_reads_blocks(self):
        message_id, content = _last_final_ai_message(
            [
                {"type": "ai", "id": "call", "tool_calls": [{"name": "search"}]},
                {
                    "type": "ai",
                    "id": "answer",
                    "content": [{"type": "text", "text": "Final answer"}],
                },
            ]
        )

        self.assertEqual((message_id, content), ("answer", "Final answer"))

    def test_running_result_contains_redacted_active_tool(self):
        result = _result_from_thread_state(
            thread_id="thread-1",
            agent_id="builtin:subagents:researcher",
            state={
                "values": {
                    "messages": [
                        {
                            "type": "ai",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "search",
                                    "args": {
                                        "query": "find this",
                                        "api_key": "do-not-leak",
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
            runs=[{"run_id": "run-1", "status": "running"}],
        )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["run_id"], "run-1")
        self.assertIn("[redacted]", result["active_tool"]["args"])
        self.assertNotIn("do-not-leak", result["active_tool"]["args"])

    def test_result_statuses(self):
        state = {"values": {"messages": [{"type": "ai", "content": "Done"}]}}
        completed = _result_from_thread_state(
            thread_id="thread-1", agent_id="agent-1", state=state, runs=[]
        )
        failed = _result_from_thread_state(
            thread_id="thread-1",
            agent_id="agent-1",
            state=state,
            runs=[{"run_id": "run-1", "status": "error"}],
        )
        empty = _result_from_thread_state(
            thread_id="thread-1",
            agent_id=None,
            state={"values": {"messages": []}},
            runs=[],
            kind="user",
        )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["kind"], "user")
        self.assertIsNone(empty["agent_id"] if empty["kind"] == "user" else "unexpected")

    def test_default_history_filters_tool_calls_and_paginates_newest_first(self):
        state = {
            "values": {
                "messages": [
                    {"type": "human", "id": "h-1", "content": "Research"},
                    {
                        "type": "ai",
                        "id": "a-call",
                        "tool_calls": [
                            {"id": "call-1", "name": "search", "args": {"q": "x"}}
                        ],
                    },
                    {
                        "type": "tool",
                        "id": "t-1",
                        "tool_call_id": "call-1",
                        "name": "search",
                        "content": "source result",
                    },
                    {"type": "ai", "id": "a-1", "content": "Final answer"},
                    {"type": "human", "id": "h-2", "content": "Follow up"},
                ]
            }
        }

        default_page = _result_from_thread_state(
            thread_id="thread-1",
            agent_id="agent-1",
            state=state,
            runs=[],
            limit=2,
            offset=0,
        )
        tool_page = _result_from_thread_state(
            thread_id="thread-1",
            agent_id="agent-1",
            state=state,
            runs=[],
            limit=10,
            offset=0,
            include=["tool_calls"],
        )

        self.assertEqual([item["id"] for item in default_page["messages"]], ["h-2", "a-1"])
        self.assertTrue(default_page["has_more"])
        self.assertEqual(default_page["next_offset"], 2)
        self.assertNotIn("content", default_page)
        self.assertEqual(default_page["messages"][0]["content"], "Follow up")
        self.assertEqual(
            [item["type"] for item in tool_page["messages"]],
            ["human", "ai", "tool", "ai", "human"],
        )
        self.assertEqual(tool_page["messages"][3]["tool_calls"][0]["name"], "search")

    def test_thread_result_schema_exposes_pagination_and_include(self):
        self.assertEqual(thread_result.args["limit"]["default"], 10)
        self.assertEqual(thread_result.args["offset"]["default"], 0)
        self.assertIn("array", str(thread_result.args["include"]))

    def test_structured_result_is_available_in_tool_message(self):
        runtime = types.SimpleNamespace(tool_call_id="thread-result-call")
        payload = {"status": "completed", "thread_id": "thread-1", "content": "Done"}

        command = _tool_result(
            runtime,
            content=json.dumps(payload),
            snapshot={"thread_id": "thread-1", "status": "completed"},
            result=payload,
            name="thread_result",
        )
        message = command.update["messages"][0]

        self.assertEqual(json.loads(message.content), payload)
        self.assertEqual(message.additional_kwargs["subagent_result"], payload)
        self.assertEqual(message.name, "thread_result")

    def test_module_exposes_thread_result_only_to_parent(self):
        module = SubagentsModule()
        parent_tools = asyncio.run(module._get_tools(None, None, config={}))
        child_tools = asyncio.run(
            module._get_tools(None, None, config={"configurable": {"subagent_id": "agent-1"}})
        )

        self.assertEqual({tool.name for tool in parent_tools}, {"subtask", "thread_result"})
        self.assertEqual(child_tools, [])

    def test_module_hides_parent_tools_when_no_ready_subagents(self):
        module = SubagentsModule()
        user = types.SimpleNamespace()

        with patch.object(
            module,
            "_ready_definitions",
            new=AsyncMock(return_value=[]),
        ):
            tools = asyncio.run(module._get_tools(user, object(), config={}))

        self.assertEqual(tools, [])

    def test_module_exposes_parent_tools_when_a_subagent_is_ready(self):
        module = SubagentsModule()
        user = types.SimpleNamespace()

        with patch.object(
            module,
            "_ready_definitions",
            new=AsyncMock(return_value=[types.SimpleNamespace()]),
        ):
            tools = asyncio.run(module._get_tools(user, object(), config={}))

        self.assertEqual({tool.name for tool in tools}, {"subtask", "thread_result"})
        self.assertEqual(thread_result.args["thread_id"]["type"], "string")


class SubagentThreadResultResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def _invoke_thread_result(
        self,
        validation_results: list[tuple[dict | None, Any, list[Any], str | None]],
        *,
        thread_id: str = "outer-thread",
        **kwargs,
    ) -> tuple[dict, AsyncMock]:
        runtime = types.SimpleNamespace(config={}, tool_call_id="thread-result-call")
        validation = AsyncMock(side_effect=validation_results)
        with (
            patch(
                "giga_agent.modules.subagents.tools.get_current_agent",
                return_value=types.SimpleNamespace(graph=object()),
            ),
            patch(
                "giga_agent.modules.subagents.tools.RuntimeResolver.from_config",
                return_value=types.SimpleNamespace(
                    user=types.SimpleNamespace(id="user-1")
                ),
            ),
            patch(
                "giga_agent.modules.subagents.tools._validate_thread_for_result",
                new=validation,
            ),
        ):
            command = await thread_result.coroutine(
                thread_id=thread_id,
                runtime=runtime,
                **kwargs,
            )

        message = command.update["messages"][0]
        return json.loads(message.content), validation

    async def test_external_thread_reads_inner_messages_and_keeps_outer_id(self):
        result, validation = await self._invoke_thread_result(
            [
                (
                    {"subagent": False},
                    {
                        "values": {
                            "inner_thread_id": "inner-thread",
                            "messages": [{"type": "ai", "content": "outer wrapper"}],
                        }
                    },
                    [],
                    None,
                ),
                (
                    {"subagent": False},
                    {
                        "values": {
                            "messages": [
                                {"type": "human", "content": "inner request"},
                                {"type": "ai", "content": "inner answer"},
                            ]
                        }
                    },
                    [],
                    None,
                ),
            ]
        )

        self.assertEqual(result["thread_id"], "outer-thread")
        self.assertEqual(
            [message["content"] for message in result["messages"]],
            ["inner answer", "inner request"],
        )
        self.assertEqual(
            [call.kwargs["thread_id"] for call in validation.await_args_list],
            ["outer-thread", "inner-thread"],
        )

    async def test_regular_thread_reads_its_own_messages(self):
        result, validation = await self._invoke_thread_result(
            [
                (
                    {"subagent": False},
                    {"values": {"messages": [{"type": "ai", "content": "answer"}]}},
                    [],
                    None,
                )
            ]
        )

        self.assertEqual(result["thread_id"], "outer-thread")
        self.assertEqual(result["messages"][0]["content"], "answer")
        validation.assert_awaited_once()

    async def test_falls_back_to_external_when_inner_is_unavailable(self):
        result, validation = await self._invoke_thread_result(
            [
                (
                    {"subagent": False},
                    {
                        "values": {
                            "inner_thread_id": "missing-inner",
                            "messages": [{"type": "ai", "content": "outer answer"}],
                        }
                    },
                    [],
                    None,
                ),
                (None, None, [], "not_found"),
            ]
        )

        self.assertEqual(result["thread_id"], "outer-thread")
        self.assertEqual(result["messages"][0]["content"], "outer answer")
        self.assertEqual(
            [call.kwargs["thread_id"] for call in validation.await_args_list],
            ["outer-thread", "missing-inner"],
        )


class SubagentThreadValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_subtask_continuation_uses_metadata_not_state_snapshot(self):
        runtime = types.SimpleNamespace(
            config={"configurable": {"thread_id": "parent-thread"}},
            tool_call_id="call-1",
        )
        definition = types.SimpleNamespace(ref="agent-1", name="Researcher")
        metadata = {
            "subagent": True,
            "agent_id": "agent-1",
            "parent_thread_id": "parent-thread",
        }
        state = types.SimpleNamespace(values={"messages": []})
        lease = types.SimpleNamespace(id="lease-1")

        async def fake_heartbeat(_user_id, _lease_id):
            return

        class NoopTask:
            def cancel(self):
                return

            def __await__(self):
                async def done():
                    return None

                return done().__await__()

        def fake_create_task(coro):
            coro.close()
            return NoopTask()

        with (
            patch(
                "giga_agent.modules.subagents.tools.get_current_agent",
                return_value=types.SimpleNamespace(graph=object()),
            ),
            patch(
                "giga_agent.modules.subagents.tools.RuntimeResolver.from_config",
                return_value=types.SimpleNamespace(user=types.SimpleNamespace(id="user-1")),
            ),
            patch(
                "giga_agent.modules.subagents.tools.get_settings",
                return_value=types.SimpleNamespace(giga_agent_runtime="cli"),
            ),
            patch(
                "giga_agent.modules.subagents.tools._validate_subagent_thread",
                new=AsyncMock(
                    return_value=(definition, metadata, state, [], None)
                ),
            ),
            patch(
                "giga_agent.modules.subagents.tools.acquire_lease",
                new=AsyncMock(return_value=lease),
            ),
            patch(
                "giga_agent.modules.subagents.tools._heartbeat",
                new=fake_heartbeat,
            ),
            patch(
                "giga_agent.modules.subagents.tools.asyncio.create_task",
                new=fake_create_task,
            ),
            patch(
                "giga_agent.modules.subagents.tools.invoke_subgraph_cli",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "giga_agent.modules.subagents.tools._result_text",
                return_value="Done",
            ),
            patch(
                "giga_agent.modules.subagents.tools.push_ui_message",
            ) as push_ui_message,
            patch(
                "giga_agent.modules.subagents.tools.cache.delete",
                new=AsyncMock(),
            ),
            patch(
                "giga_agent.modules.subagents.tools.release_lease",
                new=AsyncMock(),
            ),
        ):
            command = await subtask.coroutine(
                task="Follow up",
                runtime=runtime,
                thread_id="child-thread",
            )

        message = command.update["messages"][0]
        self.assertEqual(
            message.additional_kwargs["subagent_activity"]["status"],
            "completed",
            message.content,
        )
        self.assertEqual(push_ui_message.call_count, 2)
        self.assertTrue(
            all(call.kwargs.get("state_key") is None for call in push_ui_message.call_args_list)
        )

    async def test_non_subagent_thread_is_hidden(self):
        runtime = types.SimpleNamespace(config={})
        with (
            patch(
                "giga_agent.modules.subagents.tools.get_settings",
                return_value=types.SimpleNamespace(giga_agent_runtime="local"),
            ),
            patch(
                "giga_agent.modules.subagents.tools._inspect_server_thread",
                new=AsyncMock(
                    return_value=(
                        {"metadata": {"user_id": "user-1"}},
                        {"values": {}},
                        [],
                    )
                ),
            ),
        ):
            result = await _validate_subagent_thread(
                runtime,
                agent=object(),
                user=types.SimpleNamespace(id="user-1"),
                thread_id="thread-1",
                requested_agent_id=None,
            )

        self.assertEqual(result[-1], "not_found")

    async def test_result_validation_accepts_regular_user_thread(self):
        runtime = types.SimpleNamespace(config={})
        with (
            patch(
                "giga_agent.modules.subagents.tools.get_settings",
                return_value=types.SimpleNamespace(giga_agent_runtime="local"),
            ),
            patch(
                "giga_agent.modules.subagents.tools._inspect_server_thread",
                new=AsyncMock(
                    return_value=(
                        {"metadata": {"user_id": "user-1", "subagent": False}},
                        {"values": {"messages": []}},
                        [],
                    )
                ),
            ),
        ):
            metadata, state, runs, error = await _validate_thread_for_result(
                runtime,
                agent=object(),
                user=types.SimpleNamespace(id="user-1"),
                thread_id="ordinary-thread",
            )

        self.assertEqual(metadata["user_id"], "user-1")
        self.assertEqual(state["values"], {"messages": []})
        self.assertEqual(runs, [])
        self.assertIsNone(error)

    async def test_agent_mismatch_is_rejected(self):
        runtime = types.SimpleNamespace(config={})
        definition = types.SimpleNamespace(ref="agent-1")
        with (
            patch(
                "giga_agent.modules.subagents.tools.get_settings",
                return_value=types.SimpleNamespace(giga_agent_runtime="local"),
            ),
            patch(
                "giga_agent.modules.subagents.tools._inspect_server_thread",
                new=AsyncMock(
                    return_value=(
                        {
                            "metadata": {
                                "subagent": True,
                                "agent_id": "agent-1",
                            }
                        },
                        {"values": {}},
                        [],
                    )
                ),
            ),
            patch(
                "giga_agent.modules.subagents.tools._resolve_definition",
                new=AsyncMock(return_value=definition),
            ),
        ):
            result = await _validate_subagent_thread(
                runtime,
                agent=object(),
                user=types.SimpleNamespace(id="user-1"),
                thread_id="thread-1",
                requested_agent_id="agent-2",
            )

        self.assertEqual(result[-1], "agent_mismatch")
