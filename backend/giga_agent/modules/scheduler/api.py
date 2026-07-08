"""REST API endpoints for scheduled tasks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.scheduled_task import (
    KIND_CRON,
    KIND_ONCE,
    ScheduledTaskCreate,
    ScheduledTaskRepository,
    ScheduledTaskResponse,
    ScheduledTaskUpdate,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.core.time import default_tz
from giga_agent.scheduled.cron import compute_next_run, is_valid_cron

router = APIRouter(tags=["scheduled-tasks"])


def _resolve_schedule(
    *,
    kind: str,
    cron: str | None,
    run_at: datetime | None,
    timezone_name: str | None,
) -> datetime:
    """Validate scheduling fields and return the next run time (UTC)."""
    if kind == KIND_CRON:
        if not cron or not is_valid_cron(cron):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid cron expression",
            )
        return compute_next_run(
            cron, tz_name=timezone_name, after=datetime.now(timezone.utc)
        )

    if run_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run_at is required for a one-time task",
        )
    # A naive run_at is interpreted in the local/configured timezone, not UTC.
    dt = run_at if run_at.tzinfo else run_at.replace(tzinfo=default_tz())
    dt = dt.astimezone(timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run_at must be in the future",
        )
    return dt


@router.get("/tasks", response_model=list[ScheduledTaskResponse])
async def list_tasks(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ScheduledTaskRepository(db)
    tasks = await repo.list_by_owner(current_user.id)
    return [ScheduledTaskResponse.model_validate(t) for t in tasks]


@router.post(
    "/tasks", response_model=ScheduledTaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_task(
    payload: ScheduledTaskCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    run_at = _resolve_schedule(
        kind=payload.kind,
        cron=payload.cron,
        run_at=payload.run_at,
        timezone_name=payload.timezone,
    )
    repo = ScheduledTaskRepository(db)
    task = await repo.create(
        owner_id=current_user.id,
        name=payload.name,
        prompt=payload.prompt,
        kind=payload.kind,
        cron=payload.cron if payload.kind == KIND_CRON else None,
        timezone=payload.timezone,
        run_at=run_at,
        targets=[t.model_dump(mode="json") for t in payload.targets],
        is_enabled=payload.is_enabled,
    )
    return ScheduledTaskResponse.model_validate(task)


@router.get("/tasks/{task_id}", response_model=ScheduledTaskResponse)
async def get_task(
    task_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ScheduledTaskRepository(db)
    task = await repo.get_for_owner(task_id, current_user.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return ScheduledTaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=ScheduledTaskResponse)
async def update_task(
    task_id: uuid.UUID,
    payload: ScheduledTaskUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ScheduledTaskRepository(db)
    task = await repo.get_for_owner(task_id, current_user.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    fields: dict = {}
    if payload.name is not None:
        fields["name"] = payload.name
    if payload.prompt is not None:
        fields["prompt"] = payload.prompt
    if payload.is_enabled is not None:
        fields["is_enabled"] = payload.is_enabled
    if payload.targets is not None:
        fields["targets"] = [t.model_dump(mode="json") for t in payload.targets]

    # Recompute run_at if scheduling changed.
    kind = payload.kind or task.kind
    cron = payload.cron if payload.cron is not None else task.cron
    tz_name = payload.timezone if payload.timezone is not None else task.timezone
    schedule_changed = (
        payload.kind is not None
        or payload.cron is not None
        or payload.run_at is not None
        or payload.timezone is not None
    )
    if schedule_changed:
        run_at = _resolve_schedule(
            kind=kind, cron=cron, run_at=payload.run_at, timezone_name=tz_name
        )
        fields["kind"] = kind
        fields["cron"] = cron if kind == KIND_CRON else None
        fields["timezone"] = tz_name
        fields["run_at"] = run_at

    updated = await repo.update(task, **fields)
    return ScheduledTaskResponse.model_validate(updated)


@router.post("/tasks/{task_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_task_now_endpoint(
    task_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Trigger an immediate test run of the task (does not affect its schedule)."""
    repo = ScheduledTaskRepository(db)
    task = await repo.get_for_owner(task_id, current_user.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    from giga_agent.scheduled.runner import run_task_now

    background_tasks.add_task(run_task_now, task.id)
    return {"task_id": str(task.id), "status": "run_triggered"}


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ScheduledTaskRepository(db)
    task = await repo.get_for_owner(task_id, current_user.id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await repo.delete(task)
    return None
