import copy

from giga_agent.config import REPL_TOOLS
from giga_agent.settings import settings


def prepend_code(code: str, state: dict):
    state = copy.deepcopy(state)
    state.pop("messages")
    tools_code = []
    for tool in state["tools"]:
        tools_code.append(
            f"""
@tool_client.call_tool
def {tool["name"]}(**kwargs):
    pass
"""
        )
    for tool in REPL_TOOLS:
        tools_code.append(
            f"""
@tool_client.call_tool
def {tool.__name__}(**kwargs):
    pass
"""
        )
    tool_url = settings.internal.tool_client_api
    state.pop("tools")
    prepend = f"""import importlib
importlib.invalidate_caches()
import pandas as pd
import numpy as np
import datetime
from app.tool_client import ToolClient
tool_client = ToolClient(base_url='{tool_url}')
tool_client.set_state({repr(state)})"""
    return prepend + "\n\n".join(tools_code) + code
