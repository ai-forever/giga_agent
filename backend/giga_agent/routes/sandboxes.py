"""
API роутер для управления Sandbox провайдерами и песочницами.

Endpoints:
- POST /sandboxes/providers - Создать провайдера
- GET /sandboxes/providers - Получить провайдеров пользователя
- GET /sandboxes/providers/types - Получить доступные типы провайдеров
- GET /sandboxes/providers/{provider_id} - Получить провайдера по ID
- GET /sandboxes/providers/{provider_id}/settings-schema - Получить схему settings для типа провайдера
- PATCH /sandboxes/providers/{provider_id} - Обновить провайдера
- DELETE /sandboxes/providers/{provider_id} - Удалить провайдера (каскадно)
"""

import uuid
from typing import Annotated, Any

from cashews import cache
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.models.users import User, UserRepository
from giga_agent.models.sandbox import (
    SandboxProvider,
    SandboxProviderCreate,
    SandboxProviderUpdate,
    SandboxProviderResponse,
    SandboxProviderRepository,
)
from giga_agent.sandbox.registry import SandboxRegistry

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


# ============ Dependencies ============


async def get_provider_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SandboxProviderRepository:
    return SandboxProviderRepository(db)


# ============ Helpers ============


async def get_provider_with_owner_check(
    provider_id: uuid.UUID,
    owner_id: uuid.UUID,
    provider_repo: SandboxProviderRepository,
) -> SandboxProvider:
    """Получить провайдера с проверкой владельца."""
    provider = await provider_repo.get_by_id(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox provider not found",
        )
    if provider.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return provider


async def get_provider_with_read_check(
    provider_id: uuid.UUID,
    user_id: uuid.UUID,
    provider_repo: SandboxProviderRepository,
) -> SandboxProvider:
    provider = await provider_repo.get_by_id(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox provider not found",
        )
    readable_provider = await provider_repo.get_by_id_readable(
        provider_id,
        user_id=user_id,
    )
    if readable_provider is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return readable_provider


async def validate_provider_settings(provider_type: str, settings: dict[str, Any]) -> dict[str, Any]:
    """
    Валидировать settings через схему runtime-класса провайдера.
    Проверяет реальное подключение (API key, S3 и т.д.).
    Бросает HTTPException при ошибке валидации или подключения.
    """
    if not SandboxRegistry.is_registered(provider_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider type: '{provider_type}'. "
            f"Available: {SandboxRegistry.available_types()}",
        )
    try:
        return await SandboxRegistry.validate_settings(provider_type, settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
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
    validated_settings = await validate_provider_settings(data.type, data.settings)

    provider = await provider_repo.create(
        owner_id=current_user.id,
        provider_type=data.type,
        name=data.name,
        settings=validated_settings,
        idle_timeout=data.idle_timeout,
        is_active=data.is_active,
    )

    user = await provider_repo.db.get(User, current_user.id)
    if user is not None and user.sandbox_provider_id is None:
        user.sandbox_provider_id = provider.id
        await provider_repo.db.commit()
        await UserRepository.invalidate_cache(current_user.id)

    await cache.delete_match(f"sandboxpair:owner:{current_user.id}:*")

    return SandboxProviderRepository.to_response(provider)


@router.get("/providers", response_model=list[SandboxProviderResponse])
async def get_sandbox_providers(
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
    only_active: bool = Query(False, description="Только активные"),
):
    """Получить список провайдеров песочниц текущего пользователя."""
    providers = await provider_repo.get_readable_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [SandboxProviderRepository.to_response(p) for p in providers]


@router.get("/providers/types", response_model=list[str])
async def get_sandbox_provider_types(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Получить список доступных типов провайдеров (зарегистрированных в registry)."""
    return SandboxRegistry.available_types()


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
            f"Available: {SandboxRegistry.available_types()}",
        )

    schema_cls = SandboxRegistry.get_settings_schema(provider_type)
    return schema_cls.model_json_schema()


@router.get("/providers/{provider_id}", response_model=SandboxProviderResponse)
async def get_sandbox_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """Получить провайдера по ID."""
    provider = await get_provider_with_read_check(
        provider_id, current_user.id, provider_repo
    )
    return SandboxProviderRepository.to_response(provider)


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
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )

    update_data: dict[str, Any] = {}

    if data.name is not None:
        update_data["name"] = data.name
    if data.idle_timeout is not None:
        update_data["idle_timeout"] = data.idle_timeout
    if data.is_active is not None:
        update_data["is_active"] = data.is_active
    if data.settings is not None:
        update_data["settings"] = await validate_provider_settings(
            provider.type, data.settings
        )

    if update_data:
        provider = await provider_repo.update(provider, **update_data)

    if update_data:
        await cache.delete_match(f"sandboxpair:owner:{current_user.id}:*")

    return SandboxProviderRepository.to_response(provider)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sandbox_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[SandboxProviderRepository, Depends(get_provider_repository)],
):
    """
    Удалить провайдера песочниц.

    ВНИМАНИЕ: Каскадно удалит все sandbox'ы, привязанные к этому провайдеру!
    """
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )
    user = await provider_repo.db.get(User, current_user.id)
    if user is not None and user.sandbox_provider_id == provider.id:
        user.sandbox_provider_id = None
        await provider_repo.db.commit()
        await UserRepository.invalidate_cache(current_user.id)

    await provider_repo.delete(provider)
    await cache.delete_match(f"sandboxpair:owner:{current_user.id}:*")
