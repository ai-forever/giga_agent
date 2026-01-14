from giga_agent.auth import AuthModule
from giga_agent.core.agent.base import BaseAgent

from langchain_openai import ChatOpenAI

from giga_agent.sandbox.local_docker import LocalDockerSandbox

agent = BaseAgent(modules=[AuthModule()])

print(agent.to_json())
