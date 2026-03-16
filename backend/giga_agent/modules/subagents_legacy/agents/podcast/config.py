from typing import Literal, TypedDict

from langchain_core.messages import AnyMessage

from giga_agent.models import FileResponse
from giga_agent.modules.subagents_legacy.agents.podcast.schema import (
    MediumDialogue,
    ShortDialogue,
)


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
    audio: FileResponse
    transcript: str
