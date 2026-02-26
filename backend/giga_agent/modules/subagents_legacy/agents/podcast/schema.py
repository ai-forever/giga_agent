"""schema.py"""

from typing import Literal

from pydantic import BaseModel, Field


class DialogueItem(BaseModel):
    """Элемент диалога."""

    speaker: Literal["Ведущая (Жанна)", "Гость"]
    text: str


class ShortDialogue(BaseModel):
    """Диалог между ведущей и гостем."""

    scratchpad: str
    name_of_guest: str
    dialogue: list[DialogueItem] = Field(
        ...,
        description="Список элементов диалога, обычно от 15 до 25 реплик",
    )


class MediumDialogue(BaseModel):
    """Диалог между ведущей и гостем."""

    scratchpad: str
    name_of_guest: str
    dialogue: list[DialogueItem] = Field(
        ...,
        description="Список элементов диалога, обычно от 30 до 45 реплик",
    )
