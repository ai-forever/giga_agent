from giga_agent.modules.auth import AuthModule
from giga_agent.modules.image import ImageModule
from giga_agent.modules.repl import ReplModule
from giga_agent.modules.search import SearchModule
from giga_agent.modules.github import GitHubModule
from giga_agent.modules.vk import VKModule
from giga_agent.modules.weather import WeatherModule
from giga_agent.modules.rag import RagModule
from giga_agent.core.agent.base import BaseAgent

from giga_agent.modules.subagents_legacy.module import SubAgentLegacyModule


agent = BaseAgent(
    modules=[
        AuthModule(),
        ReplModule(),
        ImageModule(),
        SearchModule(),
        RagModule(),
        GitHubModule(),
        VKModule(),
        WeatherModule(),
        SubAgentLegacyModule(),
    ],
)

app, graph = agent.app, agent.graph
