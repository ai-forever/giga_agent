import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)


class SearchEngine(Base):
    """Search engine configuration bound to a connector (optional)."""

    __tablename__ = "core_search_engines"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_search_engines_owner_id"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_connectors.id",
            name="fk_core_search_engines_connector_id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class SearchEngineBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    connector_id: Optional[uuid.UUID] = None
    is_active: bool = True


class SearchEngineCreate(SearchEngineBase):
    check_connection: bool = True
    permissions: ResourcePermissionsPayload | None = None


class SearchEngineUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    connector_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class SearchEngineResponse(SearchEngineBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SearchEngineRepository(ACLResourceRepositoryMixin[SearchEngine]):
    """Repository for search engines."""
    resource_model = SearchEngine
    resource_type = "search_engine"

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(engine_id: uuid.UUID) -> str:
        return f"search_engine:ctx:{engine_id}"

    @staticmethod
    async def get_from_cache(
        engine_id: uuid.UUID,
    ) -> SearchEngineResponse | None:
        cached = await cache.get(SearchEngineRepository.cache_key(engine_id))
        if cached is None:
            return None
        return SearchEngineResponse.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        engine_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> SearchEngineResponse | None:
        cached = await cls.get_from_cache(engine_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id_response(engine_id, use_cache=False)

    @staticmethod
    async def invalidate_cache(engine_id: uuid.UUID) -> None:
        await cache.delete(SearchEngineRepository.cache_key(engine_id))

    async def get_by_id(self, engine_id: uuid.UUID) -> SearchEngine | None:
        result = await self.db.execute(
            select(SearchEngine).where(SearchEngine.id == engine_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_response(
        self,
        engine_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> SearchEngineResponse | None:
        if use_cache:
            cached = await self.get_from_cache(engine_id)
            if cached is not None:
                return cached

        engine = await self.get_by_id(engine_id)
        if engine is None:
            return None

        response = self.to_response(engine)
        await cache.set(
            self.cache_key(engine_id),
            response.model_dump(mode="json"),
            expire="5m",
        )
        return response

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[SearchEngine]:
        query = select(SearchEngine).where(SearchEngine.owner_id == owner_id)
        if only_active:
            query = query.where(SearchEngine.is_active == True)  # noqa: E712
        query = query.order_by(SearchEngine.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[SearchEngine]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_with_access_for_user(
        self,
        engine_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[SearchEngine, bool, bool] | None:
        return await super().get_by_id_with_access_for_user(
            engine_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

    async def get_by_id_readable(
        self,
        engine_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> SearchEngine | None:
        row = await self.get_by_id_with_access_for_user(
            engine_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        engine, can_read, _ = row
        if not can_read:
            return None
        return engine

    async def get_by_id_writable(
        self,
        engine_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> SearchEngine | None:
        row = await self.get_by_id_with_access_for_user(
            engine_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        engine, _, can_edit = row
        if not can_edit:
            return None
        return engine

    async def get_writable_ids_for_user(
        self,
        *,
        user_id: uuid.UUID,
        resource_ids: list[uuid.UUID],
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        return await ResourcePermissionRepository(self.db).list_resource_ids_with_access(
            user_id=user_id,
            resource_type="search_engine",
            resource_ids=resource_ids,
            permission="write",
            user_group_ids=user_group_ids,
        )

    async def get_by_owner_and_type(
        self,
        owner_id: uuid.UUID,
        engine_type: str,
    ) -> SearchEngine | None:
        result = await self.db.execute(
            select(SearchEngine)
            .where(SearchEngine.owner_id == owner_id)
            .where(SearchEngine.type == engine_type)
        )
        return result.scalar_one_or_none()

    async def get_by_connector(
        self,
        connector_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[SearchEngine]:
        query = select(SearchEngine).where(SearchEngine.connector_id == connector_id)
        if only_active:
            query = query.where(SearchEngine.is_active == True)  # noqa: E712
        query = query.order_by(SearchEngine.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: uuid.UUID,
        engine_type: str,
        name: Optional[str] = None,
        settings: Optional[dict] = None,
        connector_id: uuid.UUID | None = None,
        is_active: bool = True,
    ) -> SearchEngine:
        engine = SearchEngine(
            owner_id=owner_id,
            type=engine_type,
            name=name,
            settings=settings or {},
            connector_id=connector_id,
            is_active=is_active,
        )
        self.db.add(engine)
        await self.db.commit()
        await self.db.refresh(engine)
        await cache.set(
            self.cache_key(engine.id),
            self.to_response(engine).model_dump(mode="json"),
            expire="5m",
        )
        return engine

    async def update(
        self,
        engine: SearchEngine,
        **kwargs: Any,
    ) -> SearchEngine:
        for key, value in kwargs.items():
            if hasattr(engine, key) and value is not None:
                setattr(engine, key, value)
        await self.db.commit()
        await self.db.refresh(engine)
        await self.invalidate_cache(engine.id)
        return engine

    async def delete(self, engine: SearchEngine) -> None:
        engine_id = engine.id
        await ResourcePermissionRepository(self.db).revoke_all_for_resource(
            resource_type="search_engine",
            resource_id=engine_id,
            no_commit=True,
        )
        await self.db.delete(engine)
        await self.db.commit()
        await self.invalidate_cache(engine_id)

    @staticmethod
    def to_response(
        engine: SearchEngine,
        *,
        can_edit: bool = False,
    ) -> SearchEngineResponse:
        response = SearchEngineResponse.model_validate(engine)
        response.can_edit = can_edit
        return response
