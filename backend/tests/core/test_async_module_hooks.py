import asyncio
import os
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import PrivateAttr

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.tool_node import AgentToolRuntime, ToolNode
from giga_agent.core.module import BaseModule


@tool
def async_contract_tool() -> str:
    """Test tool for module hooks."""
    return "ok"


class _AsyncHooksModule(BaseModule):
    id: str = "async_hooks"
    _calls: list[str] = PrivateAttr(default_factory=list)

    @property
    def calls(self) -> list[str]:
        return self._calls

    async def get_tools(self, user, agent, *, config=None, **kwargs):
        _ = (user, agent)
        self._calls.append("get_tools")
        return [async_contract_tool]

    async def get_instructions(self, user, agent, state, config):
        _ = (user, agent, state, config)
        self._calls.append("get_instructions")
        return "async module instructions"

    def get_middleware(self):
        self._calls.append("get_middleware")
        return None


class AsyncModuleHooksTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_agent_calls_module_hooks(self):
        module = _AsyncHooksModule()
        with patch.dict(
            os.environ, {"GIGA_AGENT_SECRET_KEY": "test-secret"}, clear=False
        ):
            agent = BaseAgent(modules=[module], tools=[])
        user = types.SimpleNamespace(settings={})

        tools = await agent.get_tools(user)
        prompt = await agent.get_prompt(user)

        self.assertIn("get_middleware", module.calls)
        self.assertIn("get_tools", module.calls)
        self.assertIn("get_instructions", module.calls)
        self.assertEqual([tool_.name for tool_ in tools], ["async_contract_tool"])
        self.assertIn("async module instructions", prompt)

    async def test_tool_node_fill_tools_awaits_agent_get_tools(self):
        user = types.SimpleNamespace(id=uuid.uuid4())
        agent = types.SimpleNamespace(
            get_tools=AsyncMock(return_value=[async_contract_tool]),
        )
        node = ToolNode(tools=[], agent=agent)

        from giga_agent.core.agent.runtime_resolver import RuntimeResolver

        resolver = RuntimeResolver(user)
        config = {"configurable": {}}
        await node._fill_tools(resolver, config)

        agent.get_tools.assert_awaited_once_with(user, config=config)
        self.assertIn("async_contract_tool", node.tools_by_name)

    async def test_tool_node_python_calls_run_sequentially_with_kernel_state(self):
        agent = types.SimpleNamespace()
        node = ToolNode(tools=[], agent=agent)
        python_seen_kernel_ids: list[str | None] = []
        other_started = asyncio.Event()

        async def fake_arun_one(call, input_type, tool_runtime):
            _ = input_type
            if call["name"] == "python":
                python_seen_kernel_ids.append(tool_runtime.state.get("kernel_id"))
                if call["id"] == "1":
                    await asyncio.wait_for(other_started.wait(), timeout=1)
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content="ok",
                                tool_call_id=call["id"],
                            )
                        ],
                        "kernel_id": f"kernel-{call['id']}",
                    }
                )
            other_started.set()
            return ToolMessage(content="ok", tool_call_id=call["id"])

        node._arun_one = fake_arun_one
        tool_calls = [
            {"name": "python", "args": {}, "id": "1", "type": "tool_call"},
            {"name": "python", "args": {}, "id": "2", "type": "tool_call"},
            {"name": "other", "args": {}, "id": "3", "type": "tool_call"},
        ]
        tool_runtimes = [
            AgentToolRuntime(
                state={},
                tool_call_id=call["id"],
                config={},
                context=None,
                store=None,
                stream_writer=None,
                agent=agent,
            )
            for call in tool_calls
        ]

        outputs = await node._arun_tool_calls(tool_calls, "tool_calls", tool_runtimes)

        self.assertEqual(python_seen_kernel_ids, [None, "kernel-1"])
        self.assertIsInstance(outputs[0], Command)
        self.assertNotIn("kernel_id", outputs[0].update)
        self.assertIsInstance(outputs[1], Command)
        self.assertEqual(outputs[1].update["kernel_id"], "kernel-2")
