from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import UploadedFile

llm = load_llm().with_config(tags=["nostream"]).bind(top_p=0.2)


class ConfigSchema(TypedDict):
    save_files: bool
    print_messages: bool


class PresentationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    slides: list
    slide_map: dict
    presentation_html: UploadedFile
    images_uploaded: dict[str, UploadedFile]
    task: str
