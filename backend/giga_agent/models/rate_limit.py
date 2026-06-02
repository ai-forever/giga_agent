from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from cashews import cache
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Uuid,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models.resource_permission import RESOURCE_TYPES

# Supported rate-limit windows and their length in seconds.
PERIOD_SECONDS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
}
PERIODS = set(PERIOD_SECONDS)

# Stored in cache to distinguish "no rate limit configured" from a cache miss.
_ABSENT_SENTINEL: dict[str, bool] = {"__absent__": True}


class RateLimit(Base):
    """Rate-limit configuration bound to a resource by ``(resource_type, resource_id)``.

    Mirrors the keying of :class:`ResourcePermission` — a single table addressed by the
    resource it applies to. Either limit may be ``NULL`` (that dimension is not limited).
    """

    __tablename__ = "core_rate_limits"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            name="uq_core_rate_limits_resource",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    requests_global: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_per_user: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="minute")
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class RateLimitBase(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    requests_global: Optional[int] = Field(default=None, ge=1)
    requests_per_user: Optional[int] = Field(default=None, ge=1)
    period: str = "minute"
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class RateLimitCreate(RateLimitBase):
    pass


class RateLimitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests_global: Optional[int] = Field(default=None, ge=1)
    requests_per_user: Optional[int] = Field(default=None, ge=1)
    period: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class RateLimitResponse(RateLimitBase):
    id: uuid.UUID
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def normalize_resource_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in RESOURCE_TYPES:
        raise ValueError(
            f"Invalid resource_type: {value!r}. Allowed: {sorted(RESOURCE_TYPES)}"
        )
    return normalized


def normalize_period(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in PERIODS:
        raise ValueError(f"Invalid period: {value!r}. Allowed: {sorted(PERIODS)}")
    return normalized


class RateLimitRepository:
    """Repository for rate-limit configs with cashews-backed read caching."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(resource_type: str, resource_id: uuid.UUID) -> str:
        return f"ratelimit:cfg:{resource_type}:{resource_id}"

    @staticmethod
    async def get_from_cache(
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> RateLimitResponse | None | bool:
        """Return cached config.

        ``None`` means cache miss; ``False`` means a cached negative ("no limit");
        otherwise the cached :class:`RateLimitResponse`.
        """
        cached = await cache.get(
            RateLimitRepository.cache_key(resource_type, resource_id)
        )
        if cached is None:
            return None
        if isinstance(cached, dict) and cached.get("__absent__"):
            return False
        return RateLimitResponse.model_validate(cached)

    @classmethod
    async def get_for_resource(
        cls,
        resource_type: str,
        resource_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> RateLimitResponse | None:
        """Resolve the active rate-limit config for a resource (cached, incl. negatives)."""
        normalized_type = normalize_resource_type(resource_type)
        cached = await cls.get_from_cache(normalized_type, resource_id)
        if cached is False:
            return None
        if cached is not None:
            return cached  # type: ignore[return-value]

        row = await cls(session).get_by_resource(normalized_type, resource_id)
        if row is None or not row.is_active:
            await cache.set(
                cls.cache_key(normalized_type, resource_id),
                _ABSENT_SENTINEL,
                expire="5m",
            )
            return None
        response = cls.to_response(row)
        await cache.set(
            cls.cache_key(normalized_type, resource_id),
            response.model_dump(mode="json"),
            expire="5m",
        )
        return response

    @staticmethod
    async def invalidate_cache(resource_type: str, resource_id: uuid.UUID) -> None:
        await cache.delete(RateLimitRepository.cache_key(resource_type, resource_id))

    async def get_by_id(self, rate_limit_id: uuid.UUID) -> RateLimit | None:
        result = await self.db.execute(
            select(RateLimit).where(RateLimit.id == rate_limit_id)
        )
        return result.scalar_one_or_none()

    async def get_by_resource(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> RateLimit | None:
        result = await self.db.execute(
            select(RateLimit)
            .where(RateLimit.resource_type == resource_type)
            .where(RateLimit.resource_id == resource_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[RateLimit]:
        result = await self.db.execute(
            select(RateLimit).order_by(RateLimit.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        requests_global: int | None = None,
        requests_per_user: int | None = None,
        period: str = "minute",
        settings: dict | None = None,
        is_active: bool = True,
    ) -> RateLimit:
        normalized_type = normalize_resource_type(resource_type)
        normalized_period = normalize_period(period)
        rate_limit = RateLimit(
            resource_type=normalized_type,
            resource_id=resource_id,
            requests_global=requests_global,
            requests_per_user=requests_per_user,
            period=normalized_period,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(rate_limit)
        await self.db.commit()
        await self.db.refresh(rate_limit)
        await self.invalidate_cache(normalized_type, resource_id)
        return rate_limit

    async def update(self, rate_limit: RateLimit, **kwargs: Any) -> RateLimit:
        if "period" in kwargs and kwargs["period"] is not None:
            kwargs["period"] = normalize_period(kwargs["period"])
        for key, value in kwargs.items():
            if hasattr(rate_limit, key):
                setattr(rate_limit, key, value)
        await self.db.commit()
        await self.db.refresh(rate_limit)
        await self.invalidate_cache(rate_limit.resource_type, rate_limit.resource_id)
        return rate_limit

    async def delete(self, rate_limit: RateLimit) -> None:
        resource_type = rate_limit.resource_type
        resource_id = rate_limit.resource_id
        await self.db.delete(rate_limit)
        await self.db.commit()
        await self.invalidate_cache(resource_type, resource_id)

    @staticmethod
    def to_response(
        rate_limit: RateLimit,
        *,
        can_edit: bool = False,
    ) -> RateLimitResponse:
        response = RateLimitResponse.model_validate(rate_limit)
        response.can_edit = can_edit
        return response
