from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class MemoryFileNotFoundError(LookupError):
    """Raised when a memory file does not exist."""


class MemoryFileExistsError(FileExistsError):
    """Raised when trying to create a memory file that already exists."""


@dataclass(frozen=True)
class MemoryFileDTO:
    id: uuid.UUID
    owner_id: uuid.UUID
    path: str
    tag: str | None
    content: str
    description: str | None
    content_hash: str
    indexed_hash: str | None
    indexed_embedding_id: uuid.UUID | None
    updated_at: datetime | None


class MemoryBackend(Protocol):
    async def get(self, *, owner_id: uuid.UUID, path: str) -> MemoryFileDTO | None: ...

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        tag: str | None,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO: ...

    async def update(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO: ...

    async def delete(self, *, owner_id: uuid.UUID, path: str) -> bool: ...

    async def list(
        self,
        *,
        owner_id: uuid.UUID,
        tags: list[str] | None,
        include_global: bool,
    ) -> list[MemoryFileDTO]: ...

    async def list_all(self, *, owner_id: uuid.UUID) -> list[MemoryFileDTO]: ...

    async def list_needs_reindex(
        self,
        *,
        owner_id: uuid.UUID,
        current_embedding_id: uuid.UUID,
    ) -> list[MemoryFileDTO]: ...

    async def mark_indexed(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content_hash: str,
        embedding_id: uuid.UUID,
    ) -> None: ...

    async def reset_indexed_for_owner(self, *, owner_id: uuid.UUID) -> int: ...


__all__ = [
    "MemoryBackend",
    "MemoryFileDTO",
    "MemoryFileNotFoundError",
    "MemoryFileExistsError",
]
