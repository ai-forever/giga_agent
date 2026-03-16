from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.models import FileResponse


class ConfigSchema(TypedDict):
    save_files: bool
    print_messages: bool


class MemeState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    task: str
    meme_idea: dict
    meme_image: FileResponse
