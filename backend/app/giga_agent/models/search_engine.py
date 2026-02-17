import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT, get_session_factory


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
    pass


class SearchEngineUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    connector_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class SearchEngineResponse(SearchEngineBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SearchEngineRepository:
    """Repository for search engines."""

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
        session: AsyncSession | None = None,
        use_cache: bool = True,
    ) -> SearchEngineResponse | None:
        if use_cache:
            cached = await cls.get_from_cache(engine_id)
            if cached is not None:
                return cached

        if session is not None:
            return await cls(session).get_by_id_response(engine_id, use_cache=False)

        factory = await get_session_factory()
        async with factory() as db:
            return await cls(db).get_by_id_response(engine_id, use_cache=False)

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
        await self.db.delete(engine)
        await self.db.commit()
        await self.invalidate_cache(engine_id)

    @staticmethod
    def to_response(engine: SearchEngine) -> SearchEngineResponse:
        return SearchEngineResponse.model_validate(engine)
