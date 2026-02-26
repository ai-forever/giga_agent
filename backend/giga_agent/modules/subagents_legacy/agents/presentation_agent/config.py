from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.models import FileResponse


class ConfigSchema(TypedDict):
    save_files: bool
    print_messages: bool


class PresentationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    slides: list
    slide_map: dict
    presentation_html: FileResponse
    images_uploaded: dict[str, FileResponse]
    task: str
