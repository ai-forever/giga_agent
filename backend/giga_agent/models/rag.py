from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models.resource_permission import ResourcePermissionRepository


class RagCollection(Base):
    __tablename__ = "core_rag_collections"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_core_rag_collections_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_core_rag_collections_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    embedding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_embeddings.id",
            name="fk_core_rag_collections_embedding_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_VARIANT(), default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    documents: Mapped[list["RagDocument"]] = relationship(
        "RagDocument",
        back_populates="collection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RagDocument(Base):
    __tablename__ = "core_rag_documents"

    # id is also used as `file_id` in chunk metadata and API.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_core_rag_documents_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_rag_collections.id",
            name="fk_core_rag_documents_collection_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    sandbox_path: Mapped[str] = mapped_column(String(2048), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    collection: Mapped["RagCollection"] = relationship(
        "RagCollection",
        back_populates="documents",
    )


class RagCollectionsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[RagCollection]:
        result = await self.db.execute(
            select(RagCollection)
            .where(RagCollection.owner_id == owner_id)
            .order_by(RagCollection.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_readable_for_user(
        self,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[RagCollection]:
        permission_repo = ResourcePermissionRepository(self.db)
        access_clause = await permission_repo.build_access_clause(
            RagCollection,
            user_id=user_id,
            resource_type="rag_collection",
            permission="read",
            user_group_ids=user_group_ids,
        )
        result = await self.db.execute(
            select(RagCollection)
            .where(access_clause)
            .order_by(RagCollection.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(
        self, *, owner_id: uuid.UUID, collection_id: uuid.UUID
    ) -> RagCollection | None:
        result = await self.db.execute(
            select(RagCollection)
            .where(RagCollection.id == collection_id)
            .where(RagCollection.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_any(self, *, collection_id: uuid.UUID) -> RagCollection | None:
        result = await self.db.execute(
            select(RagCollection).where(RagCollection.id == collection_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_readable(
        self,
        *,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> RagCollection | None:
        permission_repo = ResourcePermissionRepository(self.db)
        access_clause = await permission_repo.build_access_clause(
            RagCollection,
            user_id=user_id,
            resource_type="rag_collection",
            permission="read",
            user_group_ids=user_group_ids,
        )
        result = await self.db.execute(
            select(RagCollection)
            .where(RagCollection.id == collection_id)
            .where(access_clause)
        )
        return result.scalar_one_or_none()

    async def can_write(
        self,
        *,
        user_id: uuid.UUID,
        collection_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> bool:
        return await ResourcePermissionRepository(self.db).has_access(
            user_id=user_id,
            resource_type="rag_collection",
            resource_id=collection_id,
            permission="write",
            user_group_ids=user_group_ids,
        )

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        embedding_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
    ) -> RagCollection:
        collection = RagCollection(
            owner_id=owner_id,
            name=name,
            embedding_id=embedding_id,
            metadata_=metadata or {},
        )
        self.db.add(collection)
        await self.db.commit()
        await self.db.refresh(collection)
        return collection

    async def update(
        self,
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RagCollection | None:
        collection = await self.get_by_id(
            owner_id=owner_id, collection_id=collection_id
        )
        if collection is None:
            return None
        if name is not None:
            collection.name = name
        if metadata is not None:
            collection.metadata_ = metadata
        await self.db.commit()
        await self.db.refresh(collection)
        return collection

    async def delete(self, *, owner_id: uuid.UUID, collection_id: uuid.UUID) -> bool:
        collection = await self.get_by_id(
            owner_id=owner_id, collection_id=collection_id
        )
        if collection is None:
            return False
        await self.db.delete(collection)
        await self.db.commit()
        return True


class RagDocumentsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self,
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> RagDocument | None:
        result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.id == document_id)
            .where(RagDocument.owner_id == owner_id)
            .where(RagDocument.collection_id == collection_id)
        )
        return result.scalar_one_or_none()

    async def list_by_collection(
        self,
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RagDocument]:
        result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.owner_id == owner_id)
            .where(RagDocument.collection_id == collection_id)
            .order_by(RagDocument.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_collection_any_owner(
        self,
        *,
        collection_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RagDocument]:
        result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.collection_id == collection_id)
            .order_by(RagDocument.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_id_any_owner(
        self,
        *,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> RagDocument | None:
        result = await self.db.execute(
            select(RagDocument)
            .where(RagDocument.id == document_id)
            .where(RagDocument.collection_id == collection_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        original_name: str,
        sandbox_path: str,
    ) -> RagDocument:
        doc = RagDocument(
            id=document_id,
            owner_id=owner_id,
            collection_id=collection_id,
            original_name=original_name,
            sandbox_path=sandbox_path,
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def delete(
        self,
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> bool:
        stmt = (
            delete(RagDocument)
            .where(RagDocument.id == document_id)
            .where(RagDocument.owner_id == owner_id)
            .where(RagDocument.collection_id == collection_id)
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return bool(res.rowcount)


__all__ = [
    "RagCollection",
    "RagDocument",
    "RagCollectionsRepository",
    "RagDocumentsRepository",
]
