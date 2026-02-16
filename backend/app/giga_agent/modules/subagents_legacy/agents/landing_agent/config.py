from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import UploadedFile

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
    images: Annotated[list[str], add]
    images_uploaded: dict[str, UploadedFile]
    html: UploadedFile
    done: str
