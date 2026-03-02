import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError
from sqlalchemy import String, DateTime, Uuid, ForeignKey, Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.embeddings.base import AvailableEmbeddingModel, EmbeddingModelFetchError
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.connector import Connector  # noqa: F401
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)

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
    vector_size: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # Deprecated: kept only for backward compatibility with old clients.
    # New UI should rely on dynamic JSON schema and treat settings as dict.
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
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class EmbeddingCreate(EmbeddingBase):
    check_connection: bool = True
    permissions: ResourcePermissionsPayload | None = None


class EmbeddingPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None


class EmbeddingResponse(EmbeddingBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    can_edit: bool = False
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
    vector_size: int
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class EmbeddingRepository(ACLResourceRepositoryMixin[Embedding]):
    """Repository for embeddings records and cacheable embeddings config context."""
    resource_model = Embedding
    resource_type = "embedding"

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
        try:
            return EmbeddingContext.model_validate(cached)
        except ValidationError:
            return None

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
            vector_size=embedding.vector_size,
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

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[Embedding]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_with_access_for_user(
        self,
        embedding_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[Embedding, bool, bool] | None:
        return await super().get_by_id_with_access_for_user(
            embedding_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

    async def get_by_id_readable(
        self,
        embedding_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> Embedding | None:
        row = await self.get_by_id_with_access_for_user(
            embedding_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        embedding, can_read, _ = row
        if not can_read:
            return None
        return embedding

    async def get_by_id_writable(
        self,
        embedding_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> Embedding | None:
        row = await self.get_by_id_with_access_for_user(
            embedding_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        embedding, _, can_edit = row
        if not can_edit:
            return None
        return embedding

    async def get_writable_ids_for_user(
        self,
        *,
        user_id: uuid.UUID,
        resource_ids: list[uuid.UUID],
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        return await ResourcePermissionRepository(self.db).list_resource_ids_with_access(
            user_id=user_id,
            resource_type="embedding",
            resource_ids=resource_ids,
            permission="write",
            user_group_ids=user_group_ids,
        )

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
        vector_size: int,
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
            vector_size=vector_size,
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
            if hasattr(embedding, key):
                setattr(embedding, key, value)
        await self.db.commit()
        await self.db.refresh(embedding)
        await self.invalidate_cache(embedding.id)
        return embedding

    async def delete(self, embedding: Embedding) -> None:
        embedding_id = embedding.id
        await ResourcePermissionRepository(self.db).revoke_all_for_resource(
            resource_type="embedding",
            resource_id=embedding_id,
            no_commit=True,
        )
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
    def to_response(
        embedding: Embedding,
        *,
        can_edit: bool = False,
    ) -> EmbeddingResponse:
        response = EmbeddingResponse.model_validate(embedding)
        response.can_edit = can_edit
        return response
