"""REST API endpoints for Agent Skills management."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from pydantic import BaseModel, ConfigDict, Field
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
from giga_agent.modules.skills.github import (
    GithubInstallSelection,
    GithubPreview,
    check_github_skill_updates,
    install_github_skills,
    preview_github_skills,
)
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


class GithubPreviewRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=2048)


class GithubPreviewSkill(BaseModel):
    name: str
    description: str
    path: str
    manifest_url: str
    already_installed: bool = False
    installed_commit: str | None = None


class GithubPreviewResponse(BaseModel):
    source: str
    ref: str
    commit: str
    skills: list[GithubPreviewSkill]
    warnings: list[str] = Field(default_factory=list)
    cache_state: str = "miss"
    cached_at: float | None = None


class GithubInstallSelectionRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    replace_existing: bool = False


class GithubInstallRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=2048)
    skills: list[GithubInstallSelectionRequest] = Field(
        ..., min_length=1, max_length=64
    )


class GithubInstallResultResponse(BaseModel):
    name: str
    path: str
    status: str
    error: str | None = None
    skill_id: uuid.UUID | None = None
    source_url: str | None = None
    commit: str | None = None


class GithubInstallResponse(BaseModel):
    source: str
    ref: str
    commit: str
    results: list[GithubInstallResultResponse]
    warnings: list[str] = Field(default_factory=list)
    cache_state: str = "miss"
    cached_at: float | None = None


class GithubUpdateCheckItem(BaseModel):
    skill_id: uuid.UUID
    name: str
    source: str | None = None
    ref: str | None = None
    path: str | None = None
    status: str
    available_commit: str | None = None
    error: str | None = None


class GithubUpdateCheckResponse(BaseModel):
    items: list[GithubUpdateCheckItem]


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


# --- GitHub preview/install ---


def _github_preview_response(
    preview: GithubPreview,
    installed_by_origin: dict[tuple[str, str], object],
) -> GithubPreviewResponse:
    skills = []
    for candidate in preview.skills:
        installed = installed_by_origin.get((preview.source.repository, candidate.path))
        metadata = getattr(installed, "metadata_", None) or {}
        skills.append(
            GithubPreviewSkill(
                name=candidate.name,
                description=candidate.description,
                path=candidate.path,
                manifest_url=(
                    f"https://github.com/{preview.source.repository}/blob/"
                    f"{preview.resolved_commit}/{quote(candidate.manifest_path, safe='/')}"
                ),
                already_installed=installed is not None,
                installed_commit=(
                    str(metadata["resolved_commit"])
                    if metadata.get("resolved_commit")
                    else None
                ),
            )
        )
    return GithubPreviewResponse(
        source=preview.source.normalized,
        ref=preview.resolved_ref,
        commit=preview.resolved_commit,
        skills=skills,
        warnings=list(preview.warnings),
        cache_state=preview.cache_state,
        cached_at=preview.cached_at,
    )


@router.post("/github/preview", response_model=GithubPreviewResponse)
async def preview_github(
    body: GithubPreviewRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    svc = SkillsService(db)
    try:
        preview = await preview_github_skills(
            svc,
            owner_id=current_user.id,
            source=body.source,
        )
        installed = {
            (
                str(metadata.get("github_source")),
                str(metadata.get("github_path")),
            ): skill
            for skill in await svc.repo.get_by_owner(current_user.id)
            if skill.source_type == "github"
            for metadata in [skill.metadata_ or {}]
            if isinstance(metadata.get("github_source"), str)
            and isinstance(metadata.get("github_path"), str)
        }
    except SkillInstallError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _github_preview_response(preview, installed)


@router.post("/github/install", response_model=GithubInstallResponse)
async def install_github(
    body: GithubInstallRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    sandbox = await _get_sandbox_runtime(current_user, db)
    svc = SkillsService(db)
    try:
        batch = await install_github_skills(
            svc,
            owner_id=current_user.id,
            source=body.source,
            selections=[
                GithubInstallSelection(
                    path=selection.path,
                    replace_existing=selection.replace_existing,
                )
                for selection in body.skills
            ],
            sandbox=sandbox,
        )
    except SkillInstallError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    results = []
    for result in batch.results:
        install = result.install
        results.append(
            GithubInstallResultResponse(
                name=install.skill.name if install else result.candidate.name,
                path=result.candidate.path,
                status=result.status,
                error=result.error,
                skill_id=install.skill.id if install else None,
                source_url=install.skill.source_url if install else None,
                commit=install.resolved_commit
                if install
                else batch.preview.resolved_commit,
            )
        )
    return GithubInstallResponse(
        source=batch.preview.source.normalized,
        ref=batch.preview.resolved_ref,
        commit=batch.preview.resolved_commit,
        results=results,
        warnings=list(batch.preview.warnings),
        cache_state=batch.preview.cache_state,
        cached_at=batch.preview.cached_at,
    )


@router.post("/github/updates/check", response_model=GithubUpdateCheckResponse)
async def check_github_updates(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    svc = SkillsService(db)
    items = await check_github_skill_updates(svc, owner_id=current_user.id)
    return GithubUpdateCheckResponse(
        items=[
            GithubUpdateCheckItem(
                skill_id=item.skill.id,
                name=item.skill.name,
                source=item.source,
                ref=item.ref,
                path=item.path,
                status=item.status,
                available_commit=item.available_commit,
                error=item.error,
            )
            for item in items
        ]
    )


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
