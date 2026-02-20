from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.modules.rag.models import RagCollection, RagDocument


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

    async def get_by_id(
        self, *, owner_id: uuid.UUID, collection_id: uuid.UUID
    ) -> RagCollection | None:
        result = await self.db.execute(
            select(RagCollection)
            .where(RagCollection.id == collection_id)
            .where(RagCollection.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

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
        collection = await self.get_by_id(owner_id=owner_id, collection_id=collection_id)
        if collection is None:
            return None
        if name is not None:
            collection.name = name
        if metadata is not None:
            collection.metadata_ = metadata
        await self.db.commit()
        await self.db.refresh(collection)
        return collection

    async def delete(
        self, *, owner_id: uuid.UUID, collection_id: uuid.UUID
    ) -> bool:
        collection = await self.get_by_id(owner_id=owner_id, collection_id=collection_id)
        if collection is None:
            return False
        await self.db.delete(collection)
        await self.db.commit()
        return True


class RagDocumentsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

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

