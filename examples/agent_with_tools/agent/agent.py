from giga_agent.agents.giga_agent import  GigaAgent

from agent.with_tool.module import WithToolModule

agent = GigaAgent(modules=[WithToolModule()])

graph, app = agent.graph, agent.app