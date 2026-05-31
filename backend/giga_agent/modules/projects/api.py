"""REST API endpoints for Projects."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.project import (
    ProjectCreate,
    ProjectRepository,
    ProjectResponse,
    ProjectUpdate,
)
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

logger = get_logger(__name__)

router = APIRouter(tags=["projects"])


def _project_collection_name(project_id: uuid.UUID) -> str:
    return f"__project_{project_id}__"


async def _try_create_project_collection(
    *,
    user: UserShort,
    db: AsyncSession,
    project_id: uuid.UUID,
) -> uuid.UUID | None:
    """Best-effort creation of a backing RAG collection for a project.

    Returns the collection id on success, or None if the user has no
    embedding configured (the project is still saved without a knowledge
    base — collection can be created later).
    """
    if getattr(user, "embedding_id", None) is None:
        return None
    # Imported here to avoid a cycle (rag.api → projects → rag.api).
    from giga_agent.modules.rag.api.collections import create_collection_for_user

    try:
        collection = await create_collection_for_user(
            user=user,
            db=db,
            name=_project_collection_name(project_id),
            metadata={"project_id": str(project_id)},
        )
    except Exception:
        logger.exception("Failed to create project-backed RAG collection")
        return None
    return collection.id


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

    collection_id = await _try_create_project_collection(
        user=current_user, db=db, project_id=project.id
    )
    if collection_id is not None:
        project = await repo.update(project, collection_id=collection_id)

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

    # Lazy-create a backing collection for legacy projects that were
    # created before the user configured an embedding model.
    if project.collection_id is None:
        collection_id = await _try_create_project_collection(
            user=current_user, db=db, project_id=project.id
        )
        if collection_id is not None:
            project = await repo.update(project, collection_id=collection_id)

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

    collection_id = project.collection_id
    await repo.delete(project)
    if collection_id is not None:
        try:
            collections = RagCollectionsRepository(db)
            collection = await collections.get_by_id(
                owner_id=current_user.id, collection_id=collection_id
            )
            if collection is not None:
                await db.delete(collection)
                await db.commit()
        except Exception:
            logger.exception("Failed to delete project-backed RAG collection")
    return None
