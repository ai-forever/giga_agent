"""REST API endpoints for Projects."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.project import (
    ProjectCreate,
    ProjectRepository,
    ProjectResponse,
    ProjectUpdate,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(tags=["projects"])


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ProjectRepository(db)
    projects = await repo.list_by_owner(current_user.id)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ProjectRepository(db)
    project = await repo.create(
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
    )
    if project is None:
        raise HTTPException(
            status_code=409, detail="Project with this name already exists"
        )
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ProjectRepository(db)
    project = await repo.get_for_owner(project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ProjectRepository(db)
    project = await repo.get_for_owner(project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updated = await repo.update(
        project,
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
    )
    return ProjectResponse.model_validate(updated)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = ProjectRepository(db)
    project = await repo.get_for_owner(project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await repo.delete(project)
    return None
