"""
API роутер для управления Sandbox провайдерами и песочницами.

Endpoints:
- POST /sandboxes/providers - Создать провайдера
- GET /sandboxes/providers - Получить провайдеров пользователя
- GET /sandboxes/providers/types - Получить доступные типы провайдеров
- GET /sandboxes/providers/{provider_id}/sandboxes - Получить sandbox'ы провайдера
- POST /sandboxes/providers/{provider_id}/sandboxes/{sandbox_id}/stop - Остановить sandbox провайдера
- GET /sandboxes/providers/{provider_id} - Получить провайдера по ID
- GET /sandboxes/providers/{provider_id}/settings-schema - Получить схему settings для типа провайдера
- PATCH /sandboxes/providers/{provider_id} - Обновить провайдера
- DELETE /sandboxes/providers/{provider_id} - Удалить провайдера (каскадно)
"""

import uuid
from typing import Annotated, Any

from cashews import cache
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.models.users import User, UserRepository
from giga_agent.models.file import FileRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.rag import RagDocumentsRepository
from giga_agent.modules.skills.service import SkillsService
from giga_agent.models.sandbox import (
    SandboxProvider,
    SandboxProviderCreate,
    SandboxProviderInstanceResponse,
    SandboxProviderSnapshot,
    SandboxSnapshot,
    SandboxProviderUpdate,
    SandboxProviderResponse,
    SandboxProviderRepository,
    SandboxRepository,
    SandboxStatus,
)
from giga_agent.sandbox.access import (
    ensure_provider_type_creatable_by_user,
    filter_provider_types_for_user
)
from giga_agent.sandbox.local_jupyter.dependencies import MissingDependenciesError
from giga_agent.sandbox.cleanup_tasks import cleanup_storage_files_best_effort
from giga_agent.sandbox.registry import SandboxRegistry
from giga_agent.sandbox.manager import (
    SandboxBusyError,
    SandboxManager,
    SandboxNotFoundError,
    StorageOperationError,
)
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)
from giga_agent.routes._shared.schema import (
    build_settings_schema_with_computed_defaults,
)

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


# ============ Dependencies ============


async def get_provider_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SandboxProviderRepository:
    return SandboxProviderRepository(db)


# ============ Helpers ============


async def get_provider_with_write_check(
    provider_id: uuid.UUID,
    user_id: uuid.UUID,
    provider_repo: SandboxProviderRepository,
) -> SandboxProvider:
    return await fetch_resource_with_access_check(
        resource_id=provider_id,
        user_id=user_id,
        repository=provider_repo,
        not_found_detail="Sandbox provider not found",
        require_edit=True,
    )


async def _best_effort_stop_sandboxes(
    *,
    manager: SandboxManager,
    sandboxes: list,
) -> None:
    for sandbox in sandboxes:
        try:
            await manager.stop(sandbox.id)
        except Exception:
            # Delete flows are best-effort for runtime cleanup.
            continue


def _assert_local_provider_access(provider_type: str, current_user: User) -> None:
    try:
        ensure_provider_type_creatable_by_user(
            provider_type,
            is_superuser=current_user.is_superuser,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        ) from exc


def _visible_provider_types_for_user(current_user: User) -> list[str]:
    return filter_provider_types_for_user(
        SandboxRegistry.available_types(),
        is_superuser=current_user.is_superuser,
    )


async def validate_provider_settings(
    provider_type: str,
    settings: dict[str, Any],
    *,
    current_user: User,
) -> dict[str, Any]:
    """
    Валидировать settings через схему runtime-класса провайдера.
    Проверяет реальное подключение (API key, S3 и т.д.).
    Бросает HTTPException при ошибке валидации или подключения.
    """
    if not SandboxRegistry.is_registered(provider_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider type: '{provider_type}'. "
            f"Available: {_visible_provider_types_for_user(current_user)}",
        )
    try:
        return await SandboxRegistry.validate_settings(provider_type, settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )
    except MissingDependenciesError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.to_validation_detail(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


def _to_provider_instance_response(
    *,
    owner_email: str | None,
    can_stop: bool,
    sandbox,
) -> SandboxProviderInstanceResponse:
    return SandboxProviderInstanceResponse(
        id=sandbox.id,
        provider_id=sandbox.provider_id,
        owner_id=sandbox.owner_id,
        owner_email=owner_email,
        status=sandbox.status,
        started_at=sandbox.started_at,
        stopped_at=sandbox.stopped_at,
        can_stop=can_stop,
    )


# ============ Provider Endpoints ============


@router.post(
    "/providers",
    response_model=SandboxProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sandbox_provider(
    data: SandboxProviderCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """
    Создать нового провайдера песочниц для текущего пользователя.

    Settings валидируются автоматически по схеме runtime-класса провайдера.
    """
    if data.permissions is not None:
        require_superuser(current_user)
    _assert_local_provider_access(data.type, current_user)

    validated_settings = await validate_provider_settings(
        data.type,
        data.settings,
        current_user=current_user,
    )

    provider = await provider_repo.create(
        owner_id=current_user.id,
        provider_type=data.type,
        name=data.name,
        settings=validated_settings,
        idle_timeout=data.idle_timeout,
        is_active=data.is_active,
    )
    if data.permissions is not None:
        await ResourcePermissionRepository(provider_repo.db).set_read_acl(
            resource_type="sandbox",
            resource_id=provider.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )

    user = await provider_repo.db.get(User, current_user.id)
    if user is not None and user.sandbox_provider_id is None:
        user.sandbox_provider_id = provider.id
        await provider_repo.db.commit()
        await UserRepository.invalidate_cache(current_user.id)
        await SkillsService.invalidate_list_cache(current_user.id)

    await cache.delete_match(f"sandboxpair:owner:{current_user.id}:*")

    return SandboxProviderRepository.to_response(provider, can_edit=True)


@router.get("/providers", response_model=list[SandboxProviderResponse])
async def get_sandbox_providers(
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
    only_active: bool = Query(False, description="Только активные"),
):
    """Получить список провайдеров песочниц текущего пользователя."""
    rows = await provider_repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        SandboxProviderRepository.to_response(
            provider,
            can_edit=can_edit,
        )
        for provider, can_edit in rows
    ]


@router.get("/providers/types", response_model=list[str])
async def get_sandbox_provider_types(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Получить список доступных типов провайдеров (зарегистрированных в registry)."""
    return _visible_provider_types_for_user(current_user)


@router.get(
    "/providers/{provider_id}/sandboxes",
    response_model=list[SandboxProviderInstanceResponse],
)
async def get_provider_sandboxes(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """Получить список sandbox'ов конкретного провайдера."""
    _, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=provider_id,
        user_id=current_user.id,
        repository=provider_repo,
        not_found_detail="Sandbox provider not found",
    )
    sandbox_repo = SandboxRepository(provider_repo.db)
    sandboxes = await sandbox_repo.get_by_provider(provider_id)
    owner_ids = {item.owner_id for item in sandboxes}
    owner_email_by_id: dict[uuid.UUID, str | None] = {}
    if owner_ids:
        rows = await provider_repo.db.execute(
            select(User.id, User.email).where(User.id.in_(owner_ids))
        )
        owner_email_by_id = {user_id: email for user_id, email in rows.all()}

    return [
        _to_provider_instance_response(
            owner_email=owner_email_by_id.get(item.owner_id),
            can_stop=can_edit or item.owner_id == current_user.id,
            sandbox=item,
        )
        for item in sandboxes
    ]


@router.post(
    "/providers/{provider_id}/sandboxes/{sandbox_id}/stop",
    response_model=SandboxProviderInstanceResponse,
)
async def stop_provider_sandbox(
    provider_id: uuid.UUID,
    sandbox_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """Остановить sandbox в рамках конкретного провайдера."""
    _, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=provider_id,
        user_id=current_user.id,
        repository=provider_repo,
        not_found_detail="Sandbox provider not found",
    )
    sandbox_repo = SandboxRepository(provider_repo.db)
    sandbox = await sandbox_repo.get_by_provider_and_id(
        provider_id=provider_id,
        sandbox_id=sandbox_id,
    )
    if sandbox is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox not found",
        )

    if not can_edit and sandbox.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if sandbox.status not in (SandboxStatus.STOPPED, SandboxStatus.PENDING):
        try:
            await SandboxManager(provider_repo.db).stop(sandbox_id)
        except SandboxNotFoundError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except SandboxBusyError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            ) from e
        except StorageOperationError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            ) from e

    current = await sandbox_repo.get_by_provider_and_id(
        provider_id=provider_id,
        sandbox_id=sandbox_id,
    )
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox not found",
        )
    owner = await provider_repo.db.get(User, current.owner_id)
    return _to_provider_instance_response(
        owner_email=None if owner is None else owner.email,
        can_stop=can_edit or current.owner_id == current_user.id,
        sandbox=current,
    )


@router.get(
    "/providers/types/{provider_type}/settings-schema",
    response_model=dict[str, Any],
)
async def get_sandbox_provider_settings_schema(
    provider_type: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Получить JSON Schema для settings конкретного типа провайдера.

    Полезно для фронтенда — динамическая генерация формы настроек.
    """
    if not SandboxRegistry.is_registered(provider_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider type: '{provider_type}'. "
            f"Available: {_visible_provider_types_for_user(current_user)}",
        )

    schema_cls = SandboxRegistry.get_settings_schema(provider_type)
    return build_settings_schema_with_computed_defaults(schema_cls)


@router.get("/providers/{provider_id}", response_model=SandboxProviderResponse)
async def get_sandbox_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """Получить провайдера по ID."""
    provider, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=provider_id,
        user_id=current_user.id,
        repository=provider_repo,
        not_found_detail="Sandbox provider not found",
    )
    return SandboxProviderRepository.to_response(provider, can_edit=can_edit)


@router.patch("/providers/{provider_id}", response_model=SandboxProviderResponse)
async def update_sandbox_provider(
    provider_id: uuid.UUID,
    data: SandboxProviderUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """
    Обновить провайдера песочниц.

    Если передан settings, он валидируется по схеме текущего типа провайдера.
    """
    provider = await get_provider_with_write_check(
        provider_id, current_user.id, provider_repo
    )

    update_data: dict[str, Any] = {}

    if "name" in data.model_fields_set:
        update_data["name"] = data.name
    if "idle_timeout" in data.model_fields_set:
        if data.idle_timeout is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="idle_timeout must not be null when provided",
            )
        update_data["idle_timeout"] = data.idle_timeout
    if "is_active" in data.model_fields_set:
        if data.is_active is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="is_active must not be null when provided",
            )
        update_data["is_active"] = data.is_active
    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        update_data["settings"] = await validate_provider_settings(
            provider.type,
            data.settings,
            current_user=current_user,
        )

    if update_data:
        provider = await provider_repo.update(provider, **update_data)

    if update_data:
        await cache.delete_match(f"sandboxpair:owner:{provider.owner_id}:*")

    return SandboxProviderRepository.to_response(provider, can_edit=True)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sandbox_provider(
    provider_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """
    Удалить провайдера песочниц.

    ВНИМАНИЕ: Каскадно удалит все sandbox'ы, привязанные к этому провайдеру!
    """
    provider = await get_provider_with_write_check(
        provider_id, current_user.id, provider_repo
    )
    file_repo = FileRepository(provider_repo.db)
    file_refs = await file_repo.list_storage_refs_by_provider(provider.id)
    await file_repo.delete_by_provider(provider.id)

    docs_repo = RagDocumentsRepository(provider_repo.db)
    await docs_repo.detach_by_sandbox_provider(sandbox_provider_id=provider.id)

    sandbox_snapshots_by_owner: dict[str, SandboxSnapshot] = {}
    sandbox_repo = SandboxRepository(provider_repo.db)
    provider_sandboxes = await sandbox_repo.get_by_provider_with_provider(provider.id)
    await _best_effort_stop_sandboxes(
        manager=SandboxManager(provider_repo.db),
        sandboxes=provider_sandboxes,
    )

    for owner_id in {item.owner_id for item in file_refs}:
        sandbox = await sandbox_repo.get_by_owner_and_provider(owner_id, provider.id)
        if sandbox is not None:
            pair = SandboxRepository.to_pair_snapshot(provider, sandbox)
            sandbox_snapshots_by_owner[str(owner_id)] = pair.sandbox
    user = await provider_repo.db.get(User, provider.owner_id)
    if user is not None and user.sandbox_provider_id == provider.id:
        user.sandbox_provider_id = None
        await provider_repo.db.commit()
        await UserRepository.invalidate_cache(provider.owner_id)
        await SkillsService.invalidate_list_cache(provider.owner_id)

    provider_snapshot = SandboxProviderSnapshot(
        id=provider.id,
        owner_id=provider.owner_id,
        type=provider.type,
        name=provider.name,
        settings=provider.settings or {},
        idle_timeout=provider.idle_timeout,
        is_active=provider.is_active,
        updated_at=provider.updated_at,
    )
    await provider_repo.delete(provider)
    await cache.delete_match(f"sandboxpair:owner:{provider.owner_id}:*")
    background_tasks.add_task(
        cleanup_storage_files_best_effort,
        file_refs,
        provider_snapshot=provider_snapshot,
        sandbox_snapshots_by_owner=sandbox_snapshots_by_owner,
    )
