from typing import Literal, TypedDict

from langchain_core.messages import AnyMessage

from giga_agent.modules.subagents_legacy.agents.podcast.schema import (
    MediumDialogue,
    ShortDialogue,
)
from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import UploadedFile

podcast_llm = load_llm().with_config(tags=["nostream"])


class ConfigSchema(TypedDict):
    save_files: bool


class PodcastState(TypedDict):
    messages: list[AnyMessage]
    use_messages: bool
    url: str
    podcast_text: str
    dialogue: ShortDialogue | MediumDialogue
    question: str
    tone: Literal["entertaining", "formal"]
    length: Literal["short", "medium"]
    audio: UploadedFile
    transcript: str
