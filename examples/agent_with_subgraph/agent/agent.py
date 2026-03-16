from giga_agent.agents.giga_agent import  GigaAgent

from agent.with_subgraph.module import WithSubgraphModule

agent = GigaAgent(modules=[WithSubgraphModule()])

graph, app = agent.graph, agent.app