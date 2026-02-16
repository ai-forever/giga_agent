import os
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.core.db import get_session
from giga_agent.models.file import FileRepository, FileResponse, FileType
from giga_agent.models.users import User
from giga_agent.sandbox.manager import SandboxManager

router = APIRouter(prefix="/files", tags=["files"])


async def get_file_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileRepository:
    return FileRepository(db)


def _infer_file_type(upload: UploadFile) -> FileType:
    content_type = (upload.content_type or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    if content_type == "text/html":
        return "html"
    if content_type.startswith("text/"):
        return "text"

    name = (upload.filename or "").lower()
    if name.endswith(".html") or name.endswith(".htm"):
        return "html"
    if name.endswith(".txt") or name.endswith(".md") or name.endswith(".csv"):
        return "text"
    if name.endswith(".plotly.json"):
        return "plotly_graph"
    return "other"


def _apply_thread_prefix(file_name: str, thread_id: str | None) -> str:
    if not thread_id:
        return file_name
    clean = thread_id.strip().strip("/")
    if not clean:
        return file_name
    return f"{clean}/{file_name}"


@router.post(
    "/upload", response_model=FileResponse, status_code=status.HTTP_201_CREATED
)
async def upload_file(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    thread_id: str | None = Form(default=None),
    file_type: FileType | None = Form(default=None),
    file: UploadFile = File(...),
):
    file_name = (file.filename or "").strip()
    if not file_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File name must not be empty",
        )

    content = await file.read()
    effective_file_name = _apply_thread_prefix(file_name=file_name, thread_id=thread_id)
    effective_file_type = file_type or _infer_file_type(file)

    manager = SandboxManager(db)
    try:
        created = await manager.upload_file_for_user(
            owner_id=current_user.id,
            file_name=effective_file_name,
            content=content,
            file_type=effective_file_type,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    return FileRepository.to_response(created)


@router.get("", response_model=list[FileResponse])
async def list_files(
    current_user: Annotated[User, Depends(get_current_active_user)],
    repo: Annotated[FileRepository, Depends(get_file_repository)],
    provider_id: uuid.UUID | None = Query(
        default=None,
        description="Фильтр по провайдеру",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    files = await repo.get_by_owner(
        owner_id=current_user.id,
        provider_id=provider_id,
        skip=skip,
        limit=limit,
    )
    return [FileRepository.to_response(item) for item in files]


@router.get("/{file_id}/content")
async def read_file_content(
    file_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    manager = SandboxManager(db)
    try:
        file, content_or_url = await manager.read_file_for_user(
            owner_id=current_user.id,
            file_id=file_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e

    if isinstance(content_or_url, str):
        return RedirectResponse(
            url=content_or_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    file_name = os.path.basename(file.sandbox_path.rstrip("/")) or "download.bin"
    return StreamingResponse(
        iter([content_or_url]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/content/by-path")
async def read_file_content_by_path(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    path: str = Query(..., description="Полный sandbox_path файла"),
):
    manager = SandboxManager(db)
    try:
        file, content_or_url = await manager.read_file_by_path_for_user(
            owner_id=current_user.id,
            sandbox_path=path,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e

    if isinstance(content_or_url, str):
        return RedirectResponse(
            url=content_or_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    file_name = os.path.basename(file.sandbox_path.rstrip("/")) or "download.bin"
    return StreamingResponse(
        iter([content_or_url]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    manager = SandboxManager(db)
    try:
        await manager.delete_file_for_user(owner_id=current_user.id, file_id=file_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
