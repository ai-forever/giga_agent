from __future__ import annotations

import hashlib
import uuid

from giga_agent.core.db import get_session_factory
from giga_agent.memory.backends.base import (
    MemoryFileDTO,
    MemoryFileExistsError,
    MemoryFileNotFoundError,
)
from giga_agent.memory.paths import parse_memory_path
from giga_agent.models.memory import MemoryFile, MemoryFileRepository


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _row_to_dto(row: MemoryFile) -> MemoryFileDTO:
    return MemoryFileDTO(
        id=row.id,
        owner_id=row.owner_id,
        path=row.path,
        tag=row.tag,
        content=row.content,
        description=row.description,
        content_hash=row.content_hash,
        indexed_hash=row.indexed_hash,
        indexed_embedding_id=row.indexed_embedding_id,
        updated_at=row.updated_at,
    )


class DBBackend:
    async def get(self, *, owner_id: uuid.UUID, path: str) -> MemoryFileDTO | None:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            row = await repo.get_by_path(owner_id=owner_id, path=path)
        return _row_to_dto(row) if row is not None else None

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        tag: str | None,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO:
        parse_memory_path(path)  # validate
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            existing = await repo.get_by_path(owner_id=owner_id, path=path)
            if existing is not None:
                raise MemoryFileExistsError(f"Memory file already exists: {path}")
            row = await repo.upsert(
                owner_id=owner_id,
                path=path,
                tag=tag,
                content=content,
                description=description,
                content_hash=_hash(content),
            )
        return _row_to_dto(row)

    async def update(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO:
        parsed = parse_memory_path(path)
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            existing = await repo.get_by_path(owner_id=owner_id, path=path)
            if existing is None:
                raise MemoryFileNotFoundError(f"Memory file not found: {path}")
            row = await repo.upsert(
                owner_id=owner_id,
                path=path,
                tag=parsed.tag,
                content=content,
                description=description,
                content_hash=_hash(content),
            )
        return _row_to_dto(row)

    async def delete(self, *, owner_id: uuid.UUID, path: str) -> bool:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            row = await repo.delete_by_path(owner_id=owner_id, path=path)
        return row is not None

    async def list(
        self,
        *,
        owner_id: uuid.UUID,
        tags: list[str] | None,
        include_global: bool,
    ) -> list[MemoryFileDTO]:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            rows = await repo.list_for_owner(
                owner_id=owner_id,
                tags=tags,
                include_global=include_global,
            )
        return [_row_to_dto(r) for r in rows]

    async def list_all(self, *, owner_id: uuid.UUID) -> list[MemoryFileDTO]:
        from sqlalchemy import select

        from giga_agent.models.memory import MemoryFile

        factory = await get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(MemoryFile)
                .where(MemoryFile.owner_id == owner_id)
                .order_by(MemoryFile.path)
            )
            rows = list(result.scalars().all())
        return [_row_to_dto(r) for r in rows]

    async def list_needs_reindex(
        self,
        *,
        owner_id: uuid.UUID,
        current_embedding_id: uuid.UUID,
    ) -> list[MemoryFileDTO]:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            rows = await repo.list_needs_reindex(
                owner_id=owner_id,
                current_embedding_id=current_embedding_id,
            )
        return [_row_to_dto(r) for r in rows]

    async def mark_indexed(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content_hash: str,
        embedding_id: uuid.UUID,
    ) -> None:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            row = await repo.get_by_path(owner_id=owner_id, path=path)
            if row is None:
                return
            await repo.mark_indexed(
                file_id=row.id,
                content_hash=content_hash,
                embedding_id=embedding_id,
            )

    async def reset_indexed_for_owner(self, *, owner_id: uuid.UUID) -> int:
        factory = await get_session_factory()
        async with factory() as session:
            repo = MemoryFileRepository(session)
            return await repo.reset_indexed_for_owner(owner_id=owner_id)


__all__ = ["DBBackend"]
