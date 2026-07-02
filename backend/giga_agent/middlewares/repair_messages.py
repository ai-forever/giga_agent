from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.repair import repair_dangling_tool_calls
from giga_agent.core.agent.types import AgentState, Context


class RepairMessagesMiddleware(AgentMiddleware):
    """Heal dangling tool_calls before a new run starts.

    A stopped run (frontend Stop button, Telegram reset) can leave an
    AIMessage with unanswered tool_calls in the checkpoint, which GigaChat
    rejects with 422 on the next request. The repair persists stub
    ToolMessages right after the dangling AIMessage; ordering relies on the
    callback nodes returning raw deltas so RemoveMessage reaches the channel.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = runtime, config
        delta = repair_dangling_tool_calls(state.get("messages") or [])
        if not delta:
            return None
        return {"messages": delta}
