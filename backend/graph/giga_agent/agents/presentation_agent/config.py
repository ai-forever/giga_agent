from typing import TypedDict, Annotated, List

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.utils.llm import load_llm

llm = load_llm().with_config(tags=["nostream"]).bind(top_p=0.2)


class ConfigSchema(TypedDict):
    save_files: bool
    print_messages: bool


class PresentationState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    slides: list
    slide_map: dict
    presentation_html: str
    images_base_64: dict
    task: str
