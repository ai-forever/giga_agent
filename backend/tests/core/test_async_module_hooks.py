import os
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from langchain.tools import tool
from pydantic import PrivateAttr

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.tool_node import ToolNode
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

    async def get_tools(self, user, agent):
        _ = (user, agent)
        self._calls.append("get_tools")
        return [async_contract_tool]

    async def get_instructions(self, user, agent):
        _ = (user, agent)
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
        config = {
            "configurable": {"langgraph_auth_user": {"identity": str(user.id)}},
        }

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.core.agent.tool_node.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.core.agent.tool_node.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ):
            await node._fill_tools(config)

        agent.get_tools.assert_awaited_once_with(user)
        self.assertIn("async_contract_tool", node.tools_by_name)
