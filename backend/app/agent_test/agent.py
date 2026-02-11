from giga_agent.auth import AuthModule
from giga_agent.repl import ReplModule
from giga_agent.core.agent.base import BaseAgent
from langchain_gigachat import GigaChat

from langchain_core.tools import tool


@tool
def get_weather(city: str):
    """Получает погоду в городе"""
    return {"weather": -15.4}


agent = BaseAgent(modules=[AuthModule(), ReplModule()], tools=[get_weather])

app, graph = agent.app, agent.graph
