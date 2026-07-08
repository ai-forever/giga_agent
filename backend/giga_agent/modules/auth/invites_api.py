"""API приглашений в команду.

Админ-эндпоинты (/invites) — создание/список/отзыв ссылок-приглашений.
Публичные (/join) — проверка токена и вступление в команду.

Безопасность:
- в БД хранится только SHA-256 хэш токена (утечка БД ≠ утечка инвайтов);
- публичные ответы не различают "нет такого" / "просрочен" / "исчерпан";
- принятие инвайта — одна транзакция с row-lock (гонка used_count).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session
from giga_agent.core.events import event_bus
from giga_agent.models.group import GroupRepository
from giga_agent.models.invite import (
    InviteCreate,
    InviteCreatedResponse,
    InviteRepository,
    InviteResponse,
    JoinInfo,
    JoinRequest,
    invite_to_response,
)
from giga_agent.models.resource_permission import (
    PermissionGrantItem,
    ResourcePermissionRepository,
)
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.modules.auth import security
from giga_agent.modules.auth.api import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AUTH_COOKIE_NAME,
    _collect_runtime_grant_targets_from_module_secrets,
    _collect_runtime_grant_targets_from_user_model,
    _get_user_model_by_id,
    get_current_active_user,
    get_user_repository,
    require_role,
)
from giga_agent.modules.auth.events import UserCreatedEvent

router = APIRouter(tags=["invites"])

_INVALID_INVITE = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Приглашение недействительно или истекло",
)


# ============ Админ: управление приглашениями ============


@router.post("/invites", response_model=InviteCreatedResponse)
async def create_invite(
    body: InviteCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_role(current_user, "admin")

    # Проверяем существование групп до создания.
    group_ids = list(dict.fromkeys(body.group_ids))
    if group_ids:
        group_repo = GroupRepository(db)
        existing = set(await group_repo.get_existing_group_ids(group_ids))
        missing = [str(g) for g in group_ids if g not in existing]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Groups not found: {', '.join(missing)}",
            )

    invite, token = await InviteRepository(db).create(
        data=body, created_by=current_user.id
    )
    response = invite_to_response(invite)
    return InviteCreatedResponse(
        **response.model_dump(),
        token=token,
        join_path=f"/join/{token}",
    )


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_role(current_user, "admin")
    invites = await InviteRepository(db).get_all()
    return [invite_to_response(i) for i in invites]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    require_role(current_user, "admin")
    invite = await InviteRepository(db).get_by_id(invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
        await db.commit()


# ============ Команда: сводка использования ============


@router.get("/team/usage")
async def team_usage(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    days: int = 30,
):
    """Потребление LLM по участникам за период (для страницы «Команда»)."""
    require_role(current_user, "admin")
    from giga_agent.models.usage import aggregate_usage

    days = max(1, min(days, 365))
    rows = await aggregate_usage(db, days=days)
    return {
        "days": days,
        "users": [row.model_dump(mode="json") for row in rows],
    }


# ============ Публичные: вступление по ссылке ============


@router.get("/join/{token}", response_model=JoinInfo)
async def join_info(
    token: str,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    invite = await InviteRepository(db).get_by_token(token)
    if invite is None:
        return JoinInfo(valid=False)
    usable, _ = invite.is_usable()
    if not usable:
        return JoinInfo(valid=False)
    return JoinInfo(valid=True, email=invite.email, role=invite.role)


@router.post("/join")
async def join_team(
    body: JoinRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    # Row-lock: конкурентное принятие одного инвайта сериализуется здесь.
    invite = await InviteRepository(db).get_by_token_for_update(body.token)
    if invite is None:
        raise _INVALID_INVITE
    usable, _ = invite.is_usable()
    if not usable:
        raise _INVALID_INVITE

    email = str(body.email).strip().lower()
    if invite.email and invite.email.strip().lower() != email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Приглашение выписано на другую почту",
        )
    if await user_repo.exists_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        db_user = await user_repo.create(
            email=email,
            hashed_password=security.get_password_hash(body.password),
            first_name=body.first_name,
            last_name=body.last_name,
            is_active=True,
            role=invite.role,
            commit=False,
        )

        # Онбординг «вошёл и работает»: runtime-ссылки создателя инвайта +
        # read-права на них (та же механика, что в админ-создании юзера).
        if invite.copy_runtime_ids:
            creator = await _get_user_model_by_id(db, invite.created_by)
            db_user.llm_id = creator.llm_id
            db_user.fast_llm_id = creator.fast_llm_id
            db_user.embedding_id = creator.embedding_id
            db_user.image_generator_id = creator.image_generator_id
            db_user.search_engine_id = creator.search_engine_id
            db_user.sandbox_provider_id = creator.sandbox_provider_id

            grant_targets = _collect_runtime_grant_targets_from_user_model(creator)
            if invite.copy_module_secrets:
                db_user.secrets = dict(creator.secrets or {})
                grant_targets.update(
                    await _collect_runtime_grant_targets_from_module_secrets(
                        request=request,
                        secrets=db_user.secrets,
                    )
                )
            if grant_targets:
                grants = [
                    PermissionGrantItem(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        owner_type="user",
                        owner_id=db_user.id,
                        permission="read",
                    )
                    for resource_type, resource_id in sorted(
                        grant_targets, key=lambda item: (item[0], str(item[1]))
                    )
                ]
                await ResourcePermissionRepository(db).grant_permissions(
                    items=grants, no_commit=True
                )

        group_repo = GroupRepository(db)
        for raw_gid in invite.group_ids or []:
            await group_repo.add_users(
                uuid.UUID(raw_gid), [db_user.id], commit=False
            )

        invite.used_count += 1
        await db.commit()
        await db.refresh(db_user)
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    await event_bus.publish(UserCreatedEvent(user_id=db_user.id, email=db_user.email))

    # Сразу логиним нового участника (как /token).
    access_token_expires = (
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        if ACCESS_TOKEN_EXPIRE_MINUTES
        else None
    )
    access_token = security.create_access_token(
        data={"sub": db_user.email, "user_id": str(db_user.id)},
        expires_delta=access_token_expires,
    )
    cookie_domain = get_settings().giga_agent_public_base_domain
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
        domain=cookie_domain,
    )
    return {"access_token": access_token, "token_type": "bearer"}
