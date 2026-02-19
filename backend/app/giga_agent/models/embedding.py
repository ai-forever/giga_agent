import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.embeddings.base import AvailableEmbeddingModel, EmbeddingModelFetchError
from giga_agent.models.connector import Connector  # noqa: F401

# Ensure runtimes are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401


class Embedding(Base):
    """Configured embeddings model bound to a connector."""

    __tablename__ = "core_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_embeddings_owner_id"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_connectors.id",
            name="fk_core_embeddings_connector_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    connector = relationship("Connector", lazy="joined")


class EmbeddingSettings(BaseModel):
    dimensions: Optional[int] = None
    chunk_size: Optional[int] = None
    max_retries: Optional[int] = None
    request_timeout: Optional[float] = None
    timeout: Optional[float] = None
    extra: Optional[dict[str, Any]] = None


class EmbeddingBase(BaseModel):
    type: str
    connector_id: uuid.UUID
    model_id: str
    name: Optional[str] = None
    settings: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    is_active: bool = True


class EmbeddingCreate(EmbeddingBase):
    pass


class EmbeddingUpdate(BaseModel):
    type: Optional[str] = None
    connector_id: Optional[uuid.UUID] = None
    model_id: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[EmbeddingSettings] = None
    is_active: Optional[bool] = None


class EmbeddingResponse(EmbeddingBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmbeddingContext(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    connector_id: uuid.UUID
    type: str
    model_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class EmbeddingRepository:
    """Repository for embeddings records and cacheable embeddings config context."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(embedding_id: uuid.UUID) -> str:
        return f"embedding:ctx:{embedding_id}"

    @staticmethod
    async def invalidate_cache(embedding_id: uuid.UUID) -> None:
        await cache.delete(EmbeddingRepository.cache_key(embedding_id))

    @staticmethod
    async def get_from_cache(
        embedding_id: uuid.UUID,
    ) -> EmbeddingContext | None:
        cached = await cache.get(EmbeddingRepository.cache_key(embedding_id))
        if cached is None:
            return None
        return EmbeddingContext.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        embedding_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> EmbeddingContext | None:
        cached = await cls.get_from_cache(embedding_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id_context(embedding_id, use_cache=False)

    @classmethod
    async def get_cached_context_or_db(
        cls,
        embedding_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> EmbeddingContext | None:
        return await cls.get_cached_or_db(
            embedding_id,
            session=session,
        )

    async def get_by_id(self, embedding_id: uuid.UUID) -> Embedding | None:
        result = await self.db.execute(
            select(Embedding).where(Embedding.id == embedding_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_context(
        self,
        embedding_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> EmbeddingContext | None:
        if use_cache:
            cached = await self.get_from_cache(embedding_id)
            if cached is not None:
                return cached

        embedding = await self.get_by_id(embedding_id)
        if embedding is None:
            return None

        context = EmbeddingContext(
            id=embedding.id,
            owner_id=embedding.owner_id,
            connector_id=embedding.connector_id,
            type=embedding.type,
            model_id=embedding.model_id,
            settings=embedding.settings or {},
            is_active=embedding.is_active,
        )
        await cache.set(
            self.cache_key(embedding_id),
            context.model_dump(mode="json"),
            expire="5m",
        )
        return context

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[Embedding]:
        query = select(Embedding).where(Embedding.owner_id == owner_id)
        if only_active:
            query = query.where(Embedding.is_active == True)  # noqa: E712
        query = query.order_by(Embedding.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_connector(
        self,
        connector_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[Embedding]:
        query = select(Embedding).where(Embedding.connector_id == connector_id)
        if only_active:
            query = query.where(Embedding.is_active == True)  # noqa: E712
        query = query.order_by(Embedding.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: uuid.UUID,
        embedding_type: str,
        connector_id: uuid.UUID,
        model_id: str,
        name: Optional[str] = None,
        settings: Optional[dict[str, Any]] = None,
        is_active: bool = True,
    ) -> Embedding:
        embedding = Embedding(
            owner_id=owner_id,
            type=embedding_type,
            connector_id=connector_id,
            model_id=model_id,
            name=name,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(embedding)
        await self.db.commit()
        await self.db.refresh(embedding)
        await self.invalidate_cache(embedding.id)
        return embedding

    async def update(
        self,
        embedding: Embedding,
        **kwargs: Any,
    ) -> Embedding:
        for key, value in kwargs.items():
            if hasattr(embedding, key) and value is not None:
                setattr(embedding, key, value)
        await self.db.commit()
        await self.db.refresh(embedding)
        await self.invalidate_cache(embedding.id)
        return embedding

    async def delete(self, embedding: Embedding) -> None:
        embedding_id = embedding.id
        await self.db.delete(embedding)
        await self.db.commit()
        await self.invalidate_cache(embedding_id)

    async def get_context_by_id(
        self,
        embedding_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> EmbeddingContext | None:
        return await self.get_by_id_context(embedding_id, use_cache=use_cache)

    @staticmethod
    def to_response(embedding: Embedding) -> EmbeddingResponse:
        return EmbeddingResponse.model_validate(embedding)
