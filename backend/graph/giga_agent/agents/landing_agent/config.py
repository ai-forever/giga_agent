from operator import add
from typing import TypedDict, Annotated, List, Dict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


from giga_agent.utils.llm import load_llm


llm = load_llm().with_config(tags=["nostream"])


class ConfigSchema(TypedDict):
    save_files: bool
    print_messages: bool


class LandingState(TypedDict):
    task: str
    agent_messages: Annotated[list[AnyMessage], add_messages]
    plan: str
    plan_messages: Annotated[list[AnyMessage], add_messages]
    image_messages: Annotated[list[AnyMessage], add_messages]
    image_plan_loaded: bool
    coder_messages: Annotated[list[AnyMessage], add_messages]
    coder_plan_loaded: bool
    images: Annotated[List[str], add]
    images_base_64: Dict[str, str]
    html: str
    done: str
