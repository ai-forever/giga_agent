from langgraph.config import RunnableConfig
from langgraph_sdk import get_client as get_langgraph_client
from pydantic import BaseModel

from giga_agent.conf import get_settings


def get_client(config: RunnableConfig):
    settings = get_settings()
    token = get_user_value_from_config(config, "token")
    return get_langgraph_client(
        url=settings.giga_agent_langgraph_api_url,
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

def get_user_value_from_config(config: RunnableConfig, value: str) -> str:
    auth_user = (config.get("configurable") or {}).get("langgraph_auth_user")
    if isinstance(auth_user, BaseModel):
        return getattr(auth_user, value, None)
    return auth_user.get(value)

def get_user_id_from_config(config: RunnableConfig) -> str:
    return get_user_value_from_config(config, "identity")
