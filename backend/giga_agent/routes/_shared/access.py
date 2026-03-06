from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status


async def fetch_resource_with_access_check(
    *,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    repository: Any,
    not_found_detail: str,
    require_edit: bool = False,
) -> Any:
    row = await repository.get_by_id_with_access_for_user(
        resource_id,
        user_id=user_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    resource, can_read, can_edit = row
    if require_edit and not can_edit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if not require_edit and not can_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return resource


async def fetch_resource_with_read_and_edit(
    *,
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    repository: Any,
    not_found_detail: str,
) -> tuple[Any, bool]:
    row = await repository.get_by_id_with_access_for_user(
        resource_id,
        user_id=user_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    resource, can_read, can_edit = row
    if not can_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return resource, can_edit
