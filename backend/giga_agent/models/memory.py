from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    delete,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base


class MemoryFile(Base):
    __tablename__ = "core_memory_files"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "path", name="uq_core_memory_files_owner_path"
        ),
        Index("ix_core_memory_files_owner_tag", "owner_id", "tag"),
        Index(
            "ix_core_memory_files_owner_indexed",
            "owner_id",
            "indexed_hash",
            "content_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_core_memory_files_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_embedding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class MemoryFileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_path(
        self, *, owner_id: uuid.UUID, path: str
    ) -> MemoryFile | None:
        result = await self.db.execute(
            select(MemoryFile)
            .where(MemoryFile.owner_id == owner_id)
            .where(MemoryFile.path == path)
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self,
        *,
        owner_id: uuid.UUID,
        tags: list[str] | None = None,
        include_global: bool = True,
    ) -> list[MemoryFile]:
        stmt = select(MemoryFile).where(MemoryFile.owner_id == owner_id)
        conditions = []
        if include_global:
            conditions.append(MemoryFile.tag.is_(None))
        if tags:
            conditions.append(MemoryFile.tag.in_(tags))
        if conditions:
            from sqlalchemy import or_

            stmt = stmt.where(or_(*conditions))
        else:
            stmt = stmt.where(MemoryFile.id == uuid.UUID(int=0))
        stmt = stmt.order_by(MemoryFile.path)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_needs_reindex(
        self,
        *,
        owner_id: uuid.UUID,
        current_embedding_id: uuid.UUID,
    ) -> list[MemoryFile]:
        from sqlalchemy import or_

        stmt = select(MemoryFile).where(MemoryFile.owner_id == owner_id).where(
            or_(
                MemoryFile.indexed_hash.is_(None),
                MemoryFile.indexed_hash != MemoryFile.content_hash,
                MemoryFile.indexed_embedding_id != current_embedding_id,
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        tag: str | None,
        content: str,
        description: str | None,
        content_hash: str,
    ) -> MemoryFile:
        existing = await self.get_by_path(owner_id=owner_id, path=path)
        if existing is None:
            row = MemoryFile(
                owner_id=owner_id,
                path=path,
                tag=tag,
                content=content,
                description=description,
                content_hash=content_hash,
                indexed_hash=None,
                indexed_embedding_id=None,
            )
            self.db.add(row)
            await self.db.commit()
            await self.db.refresh(row)
            return row

        if existing.content_hash != content_hash:
            existing.content = content
            existing.description = description
            existing.content_hash = content_hash
            existing.indexed_hash = None
            existing.indexed_embedding_id = None
        else:
            existing.description = description
        await self.db.commit()
        await self.db.refresh(existing)
        return existing

    async def mark_indexed(
        self,
        *,
        file_id: uuid.UUID,
        content_hash: str,
        embedding_id: uuid.UUID,
    ) -> None:
        stmt = (
            update(MemoryFile)
            .where(MemoryFile.id == file_id)
            .values(indexed_hash=content_hash, indexed_embedding_id=embedding_id)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def reset_indexed_for_owner(self, *, owner_id: uuid.UUID) -> int:
        stmt = (
            update(MemoryFile)
            .where(MemoryFile.owner_id == owner_id)
            .values(indexed_hash=None, indexed_embedding_id=None)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return int(result.rowcount or 0)

    async def delete_by_path(
        self, *, owner_id: uuid.UUID, path: str
    ) -> MemoryFile | None:
        row = await self.get_by_path(owner_id=owner_id, path=path)
        if row is None:
            return None
        await self.db.execute(
            delete(MemoryFile).where(MemoryFile.id == row.id)
        )
        await self.db.commit()
        return row


__all__ = ["MemoryFile", "MemoryFileRepository"]
