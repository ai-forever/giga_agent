import json
from uuid import uuid4
from copy import deepcopy
from typing import Optional, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.module import BaseModule


class FrontendMCPMiddleware(AgentMiddleware):
    async def after_model(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        actions = deepcopy(state["messages"][-1].tool_calls)
        if actions:
            mcp_tool_names = [tool.get("name") for tool in state.get("mcp_tools", [])]
            frontend_actions = [
                action for action in actions if action.get("name") in mcp_tool_names
            ]
            if frontend_actions:
                value = interrupt(
                    {
                        "type": "tool_call",
                        "tools": frontend_actions,
                    },
                )
            else:
                value = interrupt({"type": "approve"})
            if value.get("type") == "comment":
                tool_message = (
                    f"Пользователь оставил комментарий к твоему вызову инструмента. "
                    f'Прочитай его и реши, как действовать дальше: "{value.get("message")}"'
                )
                tools_response = [
                    ToolMessage(
                        tool_call_id=action.get("id", str(uuid4())),
                        content=json.dumps(
                            {
                                "message": tool_message,
                            },
                            ensure_ascii=False,
                        ),
                        additional_kwargs={"tool_name": action.get("name")},
                    )
                    for action in actions
                ]
                return {
                    "messages": tools_response,
                }
        return None


class FrontendMCPModule(BaseModule):
    id: str = "frontend_mcp"

    def get_middleware(self) -> Optional["AgentMiddleware"]:
        return FrontendMCPMiddleware()
