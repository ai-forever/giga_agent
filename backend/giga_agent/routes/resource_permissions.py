from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser

router = APIRouter(prefix="/resource-permissions", tags=["resource-permissions"])


async def get_permission_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ResourcePermissionRepository:
    return ResourcePermissionRepository(db)


async def _ensure_resource_exists(
    *,
    repo: ResourcePermissionRepository,
    resource_type: str,
    resource_id: uuid.UUID,
) -> None:
    normalized_resource_type = repo._normalize_resource_type(resource_type)
    resource_model = repo._resource_model_by_type(normalized_resource_type)
    result = await repo.db.execute(
        select(resource_model.id).where(resource_model.id == resource_id).limit(1)
    )
    existing_id = result.scalar_one_or_none()
    if existing_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found",
        )


@router.get(
    "/{resource_type}/{resource_id}",
    response_model=ResourcePermissionsPayload,
)
async def get_resource_permissions(
    resource_type: str,
    resource_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    permission_repo: Annotated[
        ResourcePermissionRepository, Depends(get_permission_repository)
    ],
):
    require_superuser(current_user)
    try:
        await _ensure_resource_exists(
            repo=permission_repo,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return await permission_repo.get_read_acl(
            resource_type=resource_type,
            resource_id=resource_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.put(
    "/{resource_type}/{resource_id}",
    response_model=ResourcePermissionsPayload,
)
async def set_resource_permissions(
    resource_type: str,
    resource_id: uuid.UUID,
    body: ResourcePermissionsPayload,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    permission_repo: Annotated[
        ResourcePermissionRepository, Depends(get_permission_repository)
    ],
):
    require_superuser(current_user)
    try:
        await _ensure_resource_exists(
            repo=permission_repo,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        await permission_repo.set_read_acl(
            resource_type=resource_type,
            resource_id=resource_id,
            read_user_ids=body.read_user_ids,
            read_group_ids=body.read_group_ids,
            public_read=body.public_read,
        )
        return await permission_repo.get_read_acl(
            resource_type=resource_type,
            resource_id=resource_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
