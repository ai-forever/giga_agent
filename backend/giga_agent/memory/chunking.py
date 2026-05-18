from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter


CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str


def chunk_text(text: str) -> list[Chunk]:
    if not text.strip():
        return []
    parts = _SPLITTER.split_text(text)
    return [Chunk(index=i, text=part) for i, part in enumerate(parts) if part.strip()]


__all__ = ["Chunk", "chunk_text", "CHUNK_SIZE", "CHUNK_OVERLAP"]
