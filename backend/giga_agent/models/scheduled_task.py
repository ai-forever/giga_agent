import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    delete,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT

# Task lifecycle statuses.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_DONE_NO_DELIVERY = "done_no_delivery"
STATUS_PARTIALLY_FAILED = "partially_failed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Terminal statuses for one-shot tasks (cron tasks return to pending instead).
TERMINAL_STATUSES = frozenset(
    {
        STATUS_DONE,
        STATUS_DONE_NO_DELIVERY,
        STATUS_PARTIALLY_FAILED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }
)

KIND_ONCE = "once"
KIND_CRON = "cron"


class ScheduledTask(Base):
    """Deferred or recurring task that runs the agent and delivers the result to channels."""

    __tablename__ = "core_scheduled_tasks"
    __table_args__ = (
        Index("ix_core_scheduled_tasks_status_run_at", "status", "run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_scheduled_tasks_owner_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=KIND_ONCE)
    cron: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # [{bot_id, external_chat_id, external_user_id?}]; empty -> default recipients.
    targets: Mapped[list] = mapped_column(JSON_VARIANT(), default=list)
    # Memory tags inherited from the context where the task was scheduled (e.g.
    # the Telegram chat), so the background run shares that memory scope.
    memory_tags: Mapped[list | None] = mapped_column(JSON_VARIANT(), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=STATUS_PENDING, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Rendered parts of the last run, persisted before delivery for idempotency.
    last_result: Mapped[list | None] = mapped_column(JSON_VARIANT(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class DeliveryTarget(BaseModel):
    bot_id: uuid.UUID
    external_chat_id: str
    external_user_id: str | None = None


class ScheduledTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=255)
    prompt: str = Field(..., min_length=1)
    kind: Literal["once", "cron"] = KIND_ONCE
    cron: str | None = None
    timezone: str | None = None
    run_at: datetime | None = None
    targets: list[DeliveryTarget] = Field(default_factory=list)
    is_enabled: bool = True


class ScheduledTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=255)
    prompt: str | None = Field(None, min_length=1)
    kind: Literal["once", "cron"] | None = None
    cron: str | None = None
    timezone: str | None = None
    run_at: datetime | None = None
    targets: list[DeliveryTarget] | None = None
    is_enabled: bool | None = None


class ScheduledTaskResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str | None = None
    prompt: str
    kind: str
    cron: str | None = None
    timezone: str | None = None
    run_at: datetime | None = None
    targets: list[dict[str, Any]] = Field(default_factory=list)
    is_enabled: bool
    status: str
    last_run_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScheduledTaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, task_id: uuid.UUID) -> ScheduledTask | None:
        result = await self.db.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_for_owner(
        self, task_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ScheduledTask | None:
        result = await self.db.execute(
            select(ScheduledTask).where(
                ScheduledTask.id == task_id,
                ScheduledTask.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[ScheduledTask]:
        result = await self.db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.owner_id == owner_id)
            .order_by(ScheduledTask.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str | None = None,
        prompt: str,
        kind: str = KIND_ONCE,
        cron: str | None = None,
        timezone: str | None = None,
        run_at: datetime | None = None,
        targets: list[dict[str, Any]] | None = None,
        memory_tags: list[str] | None = None,
        is_enabled: bool = True,
    ) -> ScheduledTask:
        task = ScheduledTask(
            owner_id=owner_id,
            name=name,
            prompt=prompt,
            kind=kind,
            cron=cron,
            timezone=timezone,
            run_at=run_at,
            targets=targets or [],
            memory_tags=memory_tags or None,
            is_enabled=is_enabled,
            status=STATUS_PENDING,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def update(self, task: ScheduledTask, **kwargs: Any) -> ScheduledTask:
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def delete(self, task: ScheduledTask) -> None:
        await self.db.delete(task)
        await self.db.commit()

    async def delete_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(
            delete(ScheduledTask).where(ScheduledTask.owner_id == owner_id)
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def claim_due(self, now: datetime, *, limit: int = 50) -> list[ScheduledTask]:
        """Atomically move due tasks to running and return the ones we claimed.

        Each candidate is claimed with a conditional ``UPDATE ... WHERE
        status='pending'`` and only counted when ``rowcount == 1``. This makes a
        claim safe even without the scheduler's cashews lock: under row locking
        (Postgres READ COMMITTED) or write serialization (SQLite) a given row is
        handed to exactly one worker; concurrent claimers see ``rowcount == 0``.
        """
        candidates = await self.db.execute(
            select(ScheduledTask.id)
            .where(
                ScheduledTask.status == STATUS_PENDING,
                ScheduledTask.is_enabled.is_(True),
                ScheduledTask.run_at.is_not(None),
                ScheduledTask.run_at <= now,
            )
            .order_by(ScheduledTask.run_at.asc())
            .limit(limit)
        )
        claimed_ids: list[uuid.UUID] = []
        for (task_id,) in candidates.all():
            result = await self.db.execute(
                update(ScheduledTask)
                .where(
                    ScheduledTask.id == task_id,
                    ScheduledTask.status == STATUS_PENDING,
                )
                .values(status=STATUS_RUNNING, last_run_at=now)
            )
            if (result.rowcount or 0) == 1:
                claimed_ids.append(task_id)
        await self.db.commit()

        if not claimed_ids:
            return []
        rows = await self.db.execute(
            select(ScheduledTask).where(ScheduledTask.id.in_(claimed_ids))
        )
        return list(rows.scalars().all())

    async def save_result(
        self, task: ScheduledTask, result_parts: list[dict[str, Any]] | None
    ) -> ScheduledTask:
        task.last_result = result_parts
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def mark_status(
        self,
        task: ScheduledTask,
        status: str,
        *,
        last_error: str | None = None,
        clear_result: bool = False,
    ) -> ScheduledTask:
        task.status = status
        task.last_error = last_error
        if clear_result:
            task.last_result = None
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def reschedule_cron(
        self,
        task: ScheduledTask,
        next_run_at: datetime,
        *,
        last_error: str | None = None,
    ) -> ScheduledTask:
        task.status = STATUS_PENDING
        task.run_at = next_run_at
        task.last_result = None
        task.last_error = last_error
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def reset_stale_running(self) -> int:
        """Move tasks stuck in running (e.g. after a restart) back to pending."""
        result = await self.db.execute(
            update(ScheduledTask)
            .where(ScheduledTask.status == STATUS_RUNNING)
            .values(status=STATUS_PENDING)
        )
        await self.db.commit()
        return int(result.rowcount or 0)
