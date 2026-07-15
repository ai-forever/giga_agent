"""REST API for memory files (read-only listing + manual deletion + search)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from giga_agent.core.logging import get_logger
from giga_agent.memory.backends import get_backend
from giga_agent.memory.backends.base import (
    MemoryFileDTO,
    MemoryFileExistsError,
    MemoryFileNotFoundError,
)
from giga_agent.memory.frontmatter import parse_frontmatter
from giga_agent.memory.paths import InvalidMemoryPathError, parse_memory_path
from giga_agent.memory.runtime import build_memory_service_for_user
from giga_agent.memory.service import (
    MemoryFileTooLargeError,
    SEARCH_DEFAULT_N,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user


logger = get_logger(__name__)

router = APIRouter(tags=["memory"])


class MemoryFileSummary(BaseModel):
    id: uuid.UUID
    path: str
    tag: str | None
    description: str | None
    content_hash: str
    indexed: bool
    updated_at: datetime | None


class MemoryFileDetails(MemoryFileSummary):
    content: str
    body: str


class MemoryFileCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class MemoryFileUpdate(BaseModel):
    content: str = Field(default="")


class MemoryFileUpsert(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    n: int = Field(SEARCH_DEFAULT_N, ge=1, le=20)
    tags: list[str] | None = None
    include_global: bool = True


class MemorySearchHit(BaseModel):
    path: str
    snippet: str
    score: float


class MemorySearchResponse(BaseModel):
    hits: list[MemorySearchHit]


def _to_summary(file: MemoryFileDTO) -> MemoryFileSummary:
    return MemoryFileSummary(
        id=file.id,
        path=file.path,
        tag=file.tag,
        description=file.description,
        content_hash=file.content_hash,
        indexed=file.indexed_hash == file.content_hash
        and file.indexed_hash is not None,
        updated_at=file.updated_at,
    )


def _to_details(file: MemoryFileDTO) -> MemoryFileDetails:
    fm = parse_frontmatter(file.content)
    return MemoryFileDetails(
        **_to_summary(file).model_dump(),
        content=file.content,
        body=fm.body,
    )


async def _find_file_by_id(
    *, owner_id: uuid.UUID, memory_id: uuid.UUID
) -> MemoryFileDTO:
    backend = get_backend()
    for file in await backend.list_all(owner_id=owner_id):
        if file.id == memory_id:
            return file
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Memory file not found",
    )


def _parse_path_or_400(path: str):
    try:
        return parse_memory_path(path)
    except InvalidMemoryPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/by-path", response_model=MemoryFileDetails)
async def get_memory_by_path(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    path: Annotated[
        str, Query(description="Memory file path, e.g. /memories/ABOUT.md")
    ],
) -> MemoryFileDetails:
    """Return a memory file by its virtual path (e.g. ``/memories/ABOUT.md``)."""
    _parse_path_or_400(path)
    file = await get_backend().get(owner_id=current_user.id, path=path)
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory file not found",
        )
    return _to_details(file)


@router.put("/by-path", response_model=MemoryFileDetails)
async def upsert_memory_by_path(
    payload: MemoryFileUpsert,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> MemoryFileDetails:
    """Create the memory file if it does not exist, otherwise update its content."""
    _parse_path_or_400(payload.path)
    service = await build_memory_service_for_user(current_user, include_fast_llm=True)
    existing = await get_backend().get(owner_id=current_user.id, path=payload.path)
    try:
        if existing is None:
            result = await service.create(path=payload.path, content=payload.content)
        else:
            result = await service.update(path=payload.path, content=payload.content)
    except MemoryFileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidMemoryPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except MemoryFileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except MemoryFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _to_details(result.file)


@router.get("", response_model=list[MemoryFileSummary])
async def list_memories(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    tag: Annotated[
        str | None,
        Query(description="Filter by tag (use 'global' for global memories)"),
    ] = None,
) -> list[MemoryFileSummary]:
    """List the user's memory files (summary only; no content)."""
    backend = get_backend()
    if tag is None:
        files = await backend.list_all(owner_id=current_user.id)
    elif tag == "global":
        files = await backend.list(
            owner_id=current_user.id, tags=None, include_global=True
        )
    else:
        files = await backend.list(
            owner_id=current_user.id, tags=[tag], include_global=False
        )
    return [_to_summary(f) for f in files]


@router.post("", response_model=MemoryFileDetails, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryFileCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> MemoryFileDetails:
    """Create a new memory file at the given path."""
    _parse_path_or_400(payload.path)
    service = await build_memory_service_for_user(current_user, include_fast_llm=True)
    try:
        result = await service.create(path=payload.path, content=payload.content)
    except MemoryFileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except MemoryFileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidMemoryPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _to_details(result.file)


@router.get("/{memory_id}", response_model=MemoryFileDetails)
async def get_memory(
    memory_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> MemoryFileDetails:
    """Return a single memory file with full content."""
    file = await _find_file_by_id(owner_id=current_user.id, memory_id=memory_id)
    return _to_details(file)


@router.put("/{memory_id}", response_model=MemoryFileDetails)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryFileUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> MemoryFileDetails:
    """Replace the content of an existing memory file."""
    file = await _find_file_by_id(owner_id=current_user.id, memory_id=memory_id)
    service = await build_memory_service_for_user(current_user, include_fast_llm=True)
    try:
        result = await service.update(path=file.path, content=payload.content)
    except MemoryFileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except MemoryFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _to_details(result.file)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> None:
    """Delete a single memory file (also drops its vector chunks)."""
    file = await _find_file_by_id(owner_id=current_user.id, memory_id=memory_id)
    service = await build_memory_service_for_user(current_user)
    removed = await service.delete(path=file.path)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory file not found",
        )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_memories(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> None:
    """Wipe ALL memory files for the current user (and their vectors)."""
    backend = get_backend()
    files = await backend.list_all(owner_id=current_user.id)
    service = await build_memory_service_for_user(current_user)
    for file in files:
        try:
            await service.delete(path=file.path)
        except Exception:
            logger.exception("Failed to delete memory file %s", file.path)


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: MemorySearchRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> MemorySearchResponse:
    """Semantic search over the user's memory files."""
    service = await build_memory_service_for_user(current_user)
    if not service.has_embeddings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Семантический поиск недоступен: embedding-модель не настроена "
                "для пользователя."
            ),
        )
    try:
        hits = await service.search(
            request.query,
            n=request.n,
            visible_tags=request.tags,
            include_global=request.include_global,
        )
    except Exception as exc:
        logger.exception("API search_memories failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {exc}",
        )
    return MemorySearchResponse(
        hits=[
            MemorySearchHit(path=h.path, snippet=h.snippet, score=h.score) for h in hits
        ]
    )


__all__ = ["router"]
