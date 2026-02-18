from giga_agent.modules.auth import AuthModule
from giga_agent.modules.image import ImageModule
from giga_agent.modules.repl import ReplModule
from giga_agent.modules.search import SearchModule
from giga_agent.core.agent.base import BaseAgent

from langchain_core.tools import tool

from giga_agent.modules.subagents_legacy.module import SubAgentLegacyModule
from giga_agent.modules.tool_call_interrupt.module import ToolCallInterruptModule


@tool
def get_weather(city: str):
    """Получает погоду в городе"""
    return {"weather": -15.4}


agent = BaseAgent(
    modules=[
        AuthModule(),
        ReplModule(),
        ImageModule(),
        SearchModule(),
        SubAgentLegacyModule(),
        ToolCallInterruptModule(),
    ],
    tools=[get_weather],
)

app, graph = agent.app, agent.graph
