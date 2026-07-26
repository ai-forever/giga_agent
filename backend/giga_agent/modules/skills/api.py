"""REST API endpoints for Agent Skills management."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.skill import (
    BuiltinSkillInfo,
    SkillResponse,
    SkillSummary,
    SkillUpdate,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.skills.builtins import list_builtin_skills
from giga_agent.modules.skills.service import (
    SkillInstallError,
    SkillNotFoundError,
    SkillsService,
)
from giga_agent.sandbox.manager import ProviderNotFoundError, SandboxManager
from giga_agent.sandbox.manager.file_policy import (
    MAX_SKILL_ARCHIVE_BYTES,
    FileTooLargeError,
    enforce_upload_limit,
)
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)

router = APIRouter(tags=["skills"])


async def _get_sandbox_runtime(user: UserShort, session: AsyncSession):
    resolved = await SandboxManager.get_cached_or_db(user_id=user.id, session=session)
    return SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)


async def _maybe_get_sandbox_runtime(user: UserShort, session: AsyncSession):
    try:
        return await _get_sandbox_runtime(user, session)
    except ProviderNotFoundError:
        return None
    except Exception as e:
        logger.warning("skills: failed to resolve sandbox runtime: %s", e)
        return None


# --- List ---


@router.get("/", response_model=list[SkillSummary])
async def list_skills(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _maybe_get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    return await svc.list_skills(current_user.id, sandbox)


# --- Upload ---


@router.post("/upload", response_model=SkillResponse)
async def upload_skill(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    file: UploadFile = FastAPIFile(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    try:
        enforce_upload_limit(declared_size=file.size, limit=MAX_SKILL_ARCHIVE_BYTES)
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e

    content = await file.read()
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    try:
        skill = await svc.install_from_upload(
            current_user.id, content, file.filename, sandbox
        )
    except FileTooLargeError as e:
        # Порог по факту прочитанных байт — на случай вызывающего без .size.
        raise HTTPException(status_code=413, detail=str(e)) from e
    except SkillInstallError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("upload_skill failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to install skill")

    return SkillResponse.model_validate(skill)


# --- Install built-in ---


class InstallBuiltinRequest(BaseModel):
    skill_name: str


@router.post("/install-builtin", response_model=SkillResponse)
async def install_builtin(
    body: InstallBuiltinRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    try:
        skill = await svc.install_builtin(current_user.id, body.skill_name, sandbox)
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SkillInstallError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SkillResponse.model_validate(skill)


# --- Sync local dirs (Local Jupyter only) ---


class SyncLocalRequest(BaseModel):
    dirs: list[str] = []


@router.post("/sync-local", response_model=list[SkillSummary])
async def sync_local(
    body: SyncLocalRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    skills = await svc.sync_local_dirs(current_user.id, sandbox, body.dirs or None)
    return [
        SkillSummary(
            id=s.id,
            name=s.name,
            description=s.description,
            is_enabled=s.is_enabled,
            source_type=s.source_type,
            created_at=s.created_at,
        )
        for s in skills
    ]


# --- Get skill detail ---


class SkillDetailResponse(BaseModel):
    skill: SkillResponse
    body: str
    model_config = ConfigDict(from_attributes=True)


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill_detail(
    skill_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    try:
        detail = await svc.get_skill_detail(current_user.id, skill_id, sandbox)
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return SkillDetailResponse(
        skill=SkillResponse.model_validate(detail["skill"]),
        body=detail["body"],
    )


# --- Toggle (enable/disable) ---


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    svc = SkillsService(db)
    try:
        if body.is_enabled is True:
            skill = await svc.enable_skill(current_user.id, skill_id)
        elif body.is_enabled is False:
            skill = await svc.disable_skill(current_user.id, skill_id)
        else:
            raise HTTPException(status_code=400, detail="Nothing to update")
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return SkillResponse.model_validate(skill)


# --- Delete ---


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    try:
        await svc.remove_skill(current_user.id, skill_id, sandbox)
    except SkillNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Built-in catalog ---


@router.get("/builtin/list", response_model=list[BuiltinSkillInfo])
async def list_builtin(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    builtins = list_builtin_skills()
    sandbox = await _maybe_get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    user_skills = await svc.list_skills(current_user.id, sandbox)
    installed_names = {s.name for s in user_skills}

    return [
        BuiltinSkillInfo(
            name=b["name"],
            description=b["description"],
            is_installed=b["name"] in installed_names,
        )
        for b in builtins
    ]
