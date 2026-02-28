from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.group import (
    Group,
    GroupCreate,
    GroupIdsByUserResponse,
    GroupMemberAddRequest,
    GroupRepository,
    GroupResponse,
    GroupUpdate,
)
from giga_agent.models.users import User, UserShort
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(prefix="/groups", tags=["groups"])


async def get_group_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> GroupRepository:
    return GroupRepository(db)


def require_superuser(current_user: UserShort) -> None:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


async def _get_group_or_404(group_id: uuid.UUID, repo: GroupRepository) -> Group:
    group = await repo.get_by_id(group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )
    return group


async def _ensure_user_exists(repo: GroupRepository, user_id: uuid.UUID) -> None:
    user = await repo.db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"User not found: {user_id}",
        )


def _integrity_to_422(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc.orig),
    )


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)

    owner_id = body.owner_id or current_user.id
    await _ensure_user_exists(group_repo, owner_id)

    try:
        group = await group_repo.create(
            owner_id=owner_id,
            name=body.name,
            description=body.description,
            data=body.data,
            permissions=body.permissions,
        )
    except IntegrityError as exc:
        raise _integrity_to_422(exc) from exc
    return GroupRepository.to_response(group)


@router.get("", response_model=list[GroupResponse])
async def get_groups(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    groups = await group_repo.list_all()
    return [GroupRepository.to_response(group) for group in groups]


@router.get("/by-user/{user_id}/ids", response_model=GroupIdsByUserResponse)
async def get_group_ids_by_user(
    user_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    group_ids = await group_repo.get_group_ids_by_user_id(user_id)
    return GroupIdsByUserResponse(user_id=user_id, group_ids=group_ids)


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    group = await _get_group_or_404(group_id, group_repo)
    return GroupRepository.to_response(group)


@router.patch("/{group_id}", response_model=GroupResponse)
async def patch_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    group = await _get_group_or_404(group_id, group_repo)

    update_data: dict[str, Any] = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.description is not None:
        update_data["description"] = body.description
    if body.data is not None:
        update_data["data"] = body.data
    if body.permissions is not None:
        update_data["permissions"] = body.permissions

    if update_data:
        try:
            group = await group_repo.update(group, **update_data)
        except IntegrityError as exc:
            raise _integrity_to_422(exc) from exc
    return GroupRepository.to_response(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    group = await _get_group_or_404(group_id, group_repo)
    await group_repo.delete(group)


@router.get("/{group_id}/users", response_model=list[UserShort])
async def get_group_users(
    group_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    await _get_group_or_404(group_id, group_repo)
    return await group_repo.get_group_users(group_id)


@router.post("/{group_id}/users", response_model=list[UserShort])
async def add_group_users(
    group_id: uuid.UUID,
    body: GroupMemberAddRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    await _get_group_or_404(group_id, group_repo)
    try:
        await group_repo.add_users(group_id, body.user_ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return await group_repo.get_group_users(group_id)


@router.delete("/{group_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_user(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    group_repo: Annotated[GroupRepository, Depends(get_group_repository)],
):
    require_superuser(current_user)
    await _get_group_or_404(group_id, group_repo)
    removed = await group_repo.remove_user(group_id, user_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group membership not found",
        )
