"""Журнал использования LLM (лайт-версия для страницы «Команда»).

Одна строка = один вызов модели. Пишется UsageTrackingMiddleware
(fire-and-forget), агрегируется эндпоинтом /auth/team/usage.
Не биллинг: без цен, без квот — только видимость потребления.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import BigInteger, DateTime, String, Uuid, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from giga_agent.core.db import Base


class UsageEvent(Base):
    __tablename__ = "core_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class UserUsage(BaseModel):
    user_id: uuid.UUID
    requests: int
    input_tokens: int
    output_tokens: int
    last_activity: datetime | None = None


async def aggregate_usage(session: AsyncSession, *, days: int = 30) -> list[UserUsage]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await session.execute(
        select(
            UsageEvent.user_id,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.max(UsageEvent.created_at),
        )
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.user_id)
    )
    return [
        UserUsage(
            user_id=row[0],
            requests=row[1],
            input_tokens=row[2],
            output_tokens=row[3],
            last_activity=row[4],
        )
        for row in result.all()
    ]
