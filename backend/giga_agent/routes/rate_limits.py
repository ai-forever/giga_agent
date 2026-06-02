from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.rate_limit import (
    RateLimitRepository,
    RateLimitResponse,
    normalize_period,
    normalize_resource_type,
)
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser

router = APIRouter(prefix="/rate-limits", tags=["rate-limits"])


class RateLimitUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests_global: Optional[int] = Field(default=None, ge=1)
    requests_per_user: Optional[int] = Field(default=None, ge=1)
    period: str = "minute"
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


async def get_rate_limit_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> RateLimitRepository:
    return RateLimitRepository(db)


async def _ensure_resource_exists(
    *,
    db: AsyncSession,
    resource_type: str,
    resource_id: uuid.UUID,
) -> None:
    permission_repo = ResourcePermissionRepository(db)
    resource_model = permission_repo._resource_model_by_type(resource_type)
    result = await db.execute(
        select(resource_model.id).where(resource_model.id == resource_id).limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )


@router.get("", response_model=list[RateLimitResponse])
async def list_rate_limits(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    rate_limit_repo: Annotated[RateLimitRepository, Depends(get_rate_limit_repository)],
) -> list[RateLimitResponse]:
    require_superuser(current_user)
    rows = await rate_limit_repo.list_all()
    return [RateLimitRepository.to_response(row, can_edit=True) for row in rows]


@router.get(
    "/{resource_type}/{resource_id}",
    response_model=RateLimitResponse | None,
)
async def get_rate_limit(
    resource_type: str,
    resource_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    rate_limit_repo: Annotated[RateLimitRepository, Depends(get_rate_limit_repository)],
) -> RateLimitResponse | None:
    require_superuser(current_user)
    try:
        normalized_type = normalize_resource_type(resource_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    row = await rate_limit_repo.get_by_resource(normalized_type, resource_id)
    if row is None:
        return None
    return RateLimitRepository.to_response(row, can_edit=True)


@router.put(
    "/{resource_type}/{resource_id}",
    response_model=RateLimitResponse,
)
async def upsert_rate_limit(
    resource_type: str,
    resource_id: uuid.UUID,
    body: RateLimitUpsert,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    rate_limit_repo: Annotated[RateLimitRepository, Depends(get_rate_limit_repository)],
) -> RateLimitResponse:
    require_superuser(current_user)
    try:
        normalized_type = normalize_resource_type(resource_type)
        normalize_period(body.period)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await _ensure_resource_exists(
        db=rate_limit_repo.db,
        resource_type=normalized_type,
        resource_id=resource_id,
    )

    existing = await rate_limit_repo.get_by_resource(normalized_type, resource_id)
    if existing is None:
        row = await rate_limit_repo.create(
            resource_type=normalized_type,
            resource_id=resource_id,
            requests_global=body.requests_global,
            requests_per_user=body.requests_per_user,
            period=body.period,
            settings=body.settings,
            is_active=body.is_active,
        )
    else:
        row = await rate_limit_repo.update(
            existing,
            requests_global=body.requests_global,
            requests_per_user=body.requests_per_user,
            period=body.period,
            settings=body.settings,
            is_active=body.is_active,
        )
    return RateLimitRepository.to_response(row, can_edit=True)


@router.delete(
    "/{resource_type}/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rate_limit(
    resource_type: str,
    resource_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    rate_limit_repo: Annotated[RateLimitRepository, Depends(get_rate_limit_repository)],
) -> None:
    require_superuser(current_user)
    try:
        normalized_type = normalize_resource_type(resource_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    existing = await rate_limit_repo.get_by_resource(normalized_type, resource_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rate limit not found"
        )
    await rate_limit_repo.delete(existing)
