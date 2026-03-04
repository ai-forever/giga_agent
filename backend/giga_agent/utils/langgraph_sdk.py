from langgraph.config import RunnableConfig
from langgraph_sdk import get_client as get_langgraph_client

from giga_agent.conf import get_settings


def get_client(config: RunnableConfig):
    settings = get_settings()
    if settings.giga_agent_langgraph_api_url:
        # If GIGA_AGENT_LANGGRAPH_API_U
        return get_langgraph_client(
            url=settings.giga_agent_langgraph_api_url,
            headers={
                "Authorization": f"Bearer {config['configurable']['langgraph_auth_user']['token']}",
            },
        )
    else:
        return get_langgraph_client()
