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


class Connector(Base):
    """Connector record for external services (OpenAI, GigaChat, Tavily, ...)."""

    __tablename__ = "core_connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_connectors_owner_id"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ConnectorBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ConnectorCreate(ConnectorBase):
    pass


class ConnectorUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class ConnectorResponse(ConnectorBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectorRepository:
    """Repository for connector records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(connector_id: uuid.UUID) -> str:
        return f"connector:ctx:{connector_id}"

    @staticmethod
    async def get_from_cache(connector_id: uuid.UUID) -> ConnectorResponse | None:
        cached = await cache.get(ConnectorRepository.cache_key(connector_id))
        if cached is None:
            return None
        return ConnectorResponse.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        connector_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> ConnectorResponse | None:
        cached = await cls.get_from_cache(connector_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id_response(connector_id, use_cache=False)

    @staticmethod
    async def invalidate_cache(connector_id: uuid.UUID) -> None:
        await cache.delete(ConnectorRepository.cache_key(connector_id))

    async def get_by_id(self, connector_id: uuid.UUID) -> Connector | None:
        result = await self.db.execute(
            select(Connector).where(Connector.id == connector_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_response(
        self,
        connector_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> ConnectorResponse | None:
        if use_cache:
            cached = await self.get_from_cache(connector_id)
            if cached is not None:
                return cached

        connector = await self.get_by_id(connector_id)
        if connector is None:
            return None

        response = self.to_response(connector)
        await cache.set(
            self.cache_key(connector_id),
            response.model_dump(mode="json"),
            expire="5m",
        )
        return response

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[Connector]:
        query = select(Connector).where(Connector.owner_id == owner_id)
        if only_active:
            query = query.where(Connector.is_active == True)  # noqa: E712
        query = query.order_by(Connector.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: uuid.UUID,
        connector_type: str,
        name: Optional[str] = None,
        settings: Optional[dict[str, Any]] = None,
        is_active: bool = True,
    ) -> Connector:
        connector = Connector(
            owner_id=owner_id,
            type=connector_type,
            name=name,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(connector)
        await self.db.commit()
        await self.db.refresh(connector)
        await cache.set(
            self.cache_key(connector.id),
            self.to_response(connector).model_dump(mode="json"),
            expire="5m",
        )
        return connector

    async def update(
        self,
        connector: Connector,
        **kwargs: Any,
    ) -> Connector:
        for key, value in kwargs.items():
            if hasattr(connector, key) and value is not None:
                setattr(connector, key, value)
        await self.db.commit()
        await self.db.refresh(connector)
        await self.invalidate_cache(connector.id)
        return connector

    async def delete(self, connector: Connector) -> None:
        connector_id = connector.id
        await self.db.delete(connector)
        await self.db.commit()
        await self.invalidate_cache(connector_id)

    @staticmethod
    def to_response(connector: Connector) -> ConnectorResponse:
        return ConnectorResponse.model_validate(connector)
