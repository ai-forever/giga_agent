import os

from giga_agent.agents.giga_agent import GigaAgent
from openinference.instrumentation.langchain import LangChainInstrumentor

from phoenix.otel import register

os.environ["PHOENIX_API_KEY"] = ""
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "http://localhost:6006/v1/"
# os.environ["PHOENIX_CLIENT_HEADERS"] = f"api_key="

tracer_provider = register(
    project_name="default", endpoint="http://localhost:6006/v1/traces", batch=True
)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

agent = GigaAgent()
graph, app = (
    agent.graph,
    agent.app,
)
