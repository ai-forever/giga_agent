"""
API роутер для управления LLM моделями и провайдерами.

Endpoints:
- POST /llms - Создать LLM + Провайдера (в одной ручке)
- GET /llms - Получить доступные LLM
- GET /llms/{llm_id} - Получить LLM по ID
- PATCH /llms/{llm_id} - Изменить LLM + провайдера
- DELETE /llms/{llm_id} - Удалить LLM
- GET /llms/providers - Получить доступные провайдеры
- GET /llms/providers/types - Получить список типов провайдеров
- GET /llms/providers/{provider_id} - Получить провайдера по ID
- GET /llms/providers/{provider_id}/models - Получить доступные модели по провайдеру
- PATCH /llms/providers/{provider_id} - Обновить провайдера
- DELETE /llms/providers/{provider_id} - Удалить провайдера (каскадно)
- POST /llms/providers/models/fetch - Получить модели по настройкам (без создания провайдера)
"""

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.auth.api import get_current_active_user
from giga_agent.models.users import User
from giga_agent.models.llm import (
    LLM,
    LLMProvider,
    LLMProviderType,
    LLMProviderRepository,
    LLMRepository,
    LLMProviderUpdate,
    LLMProviderResponse,
    LLMProviderSettings,
    LLMResponse,
    LLMSettings,
    AvailableModel,
    ModelFetchError,
)

router = APIRouter(prefix="/llms", tags=["llms"])


# ============ Pydantic Schemas для комбинированных операций ============


class LLMWithProviderCreate(BaseModel):
    """
    Схема для создания LLM вместе с провайдером.
    
    - Если указан provider_id и другие данные провайдера — провайдер будет обновлён.
    - Если указан только provider_id — используется существующий провайдер без изменений.
    - Если указан provider_type (без provider_id) — создаётся новый провайдер.
    """

    # Использование/обновление существующего провайдера
    provider_id: Optional[uuid.UUID] = Field(
        None, description="ID существующего провайдера (если указан вместе с другими полями провайдера — провайдер обновится)"
    )

    # Данные для создания/обновления провайдера
    provider_type: Optional[str] = Field(
        None,
        description="Тип провайдера (openai, anthropic, gigachat, ollama, google, deepseek, custom)",
    )
    provider_name: Optional[str] = Field(None, description="Название провайдера")
    provider_settings: LLMProviderSettings = Field(
        default_factory=LLMProviderSettings, description="Настройки провайдера"
    )

    # Данные LLM
    model_id: str = Field(..., description="ID модели у провайдера")
    llm_name: Optional[str] = Field(None, description="Название LLM")
    llm_settings: LLMSettings = Field(
        default_factory=LLMSettings, description="Настройки LLM"
    )
    parallel_calls: int = Field(1, description="Количество параллельных вызовов")
    is_active: bool = Field(True, description="Активен ли LLM")


class LLMWithProviderResponse(BaseModel):
    """Ответ с LLM и провайдером"""

    llm: LLMResponse
    provider: LLMProviderResponse


class LLMWithProviderUpdate(BaseModel):
    """
    Схема для обновления LLM вместе с провайдером.
    
    Логика работы с провайдером:
    - Если указан provider_id — переключиться на указанный провайдер (и обновить его, если переданы другие поля).
    - Если указан provider_type (без provider_id) — создать нового провайдера и привязать к нему LLM.
    - Если не указаны ни provider_id, ни provider_type — обновить текущий провайдер LLM переданными полями.
    """

    # Смена/создание провайдера
    provider_id: Optional[uuid.UUID] = Field(
        None, description="ID провайдера для переключения (если указан — LLM привяжется к этому провайдеру)"
    )

    # Данные провайдера (для создания нового или обновления существующего)
    provider_type: Optional[str] = Field(None, description="Тип провайдера (если без provider_id — создаст нового)")
    provider_name: Optional[str] = Field(None, description="Название провайдера")
    provider_settings: Optional[LLMProviderSettings] = Field(
        None, description="Настройки провайдера"
    )
    provider_is_active: Optional[bool] = Field(None, description="Активен ли провайдер")

    # Данные LLM (опциональные)
    model_id: Optional[str] = Field(None, description="ID модели у провайдера")
    llm_name: Optional[str] = Field(None, description="Название LLM")
    llm_settings: Optional[LLMSettings] = Field(None, description="Настройки LLM")
    parallel_calls: Optional[int] = Field(
        None, description="Количество параллельных вызовов"
    )
    is_active: Optional[bool] = Field(None, description="Активен ли LLM")


class FetchModelsRequest(BaseModel):
    """Схема для запроса моделей по настройкам провайдера"""

    provider_type: str = Field(..., description="Тип провайдера")
    settings: LLMProviderSettings = Field(
        ..., description="Настройки провайдера для подключения"
    )


# ============ Dependencies ============


async def get_llm_provider_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> LLMProviderRepository:
    return LLMProviderRepository(db)


async def get_llm_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> LLMRepository:
    return LLMRepository(db)


# ============ Helper Functions ============


async def get_llm_with_owner_check(
    llm_id: uuid.UUID,
    owner_id: uuid.UUID,
    llm_repo: LLMRepository,
) -> LLM:
    """Получить LLM с проверкой владельца"""
    llm = await llm_repo.get_by_id(llm_id)
    if not llm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM not found",
        )
    if llm.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return llm


async def get_provider_with_owner_check(
    provider_id: uuid.UUID,
    owner_id: uuid.UUID,
    provider_repo: LLMProviderRepository,
) -> LLMProvider:
    """Получить провайдера с проверкой владельца"""
    provider = await provider_repo.get_by_id(provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    if provider.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return provider


# ============ LLM Endpoints ============


@router.post(
    "", response_model=LLMWithProviderResponse, status_code=status.HTTP_201_CREATED
)
async def create_llm_with_provider(
    data: LLMWithProviderCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
):
    """
    Создать LLM вместе с провайдером.

    - Если указан provider_id и другие данные провайдера — провайдер обновляется.
    - Если указан только provider_id — используется существующий провайдер без изменений.
    - Если указан provider_type (и не указан provider_id) — создаётся новый провайдер.
    """
    if data.provider_id:
        # Получаем существующий провайдер
        provider = await get_provider_with_owner_check(
            data.provider_id, current_user.id, provider_repo
        )
        
        # Проверяем, есть ли данные для обновления провайдера
        provider_updates = {}
        if data.provider_type is not None:
            provider_updates["type"] = data.provider_type
        if data.provider_name is not None:
            provider_updates["name"] = data.provider_name
        if data.provider_settings is not None:
            settings_dict = data.provider_settings.model_dump(exclude_none=True)
            if settings_dict:  # Обновляем только если есть непустые настройки
                provider_updates["settings"] = settings_dict
        
        # Обновляем провайдера если есть изменения
        if provider_updates:
            provider = await provider_repo.update(provider, **provider_updates)
    elif data.provider_type:
        # Создаём нового провайдера
        provider = await provider_repo.create(
            owner_id=current_user.id,
            provider_type=data.provider_type,
            name=data.provider_name,
            settings=(
                data.provider_settings.model_dump(exclude_none=True)
                if data.provider_settings
                else {}
            ),
            is_active=True,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either provider_id or provider_type must be specified",
        )

    # Создаём LLM
    llm = await llm_repo.create(
        owner_id=current_user.id,
        provider_id=provider.id,
        model_id=data.model_id,
        name=data.llm_name,
        settings=(
            data.llm_settings.model_dump(exclude_none=True) if data.llm_settings else {}
        ),
        is_active=data.is_active,
    )

    # Обновляем parallel_calls если указан
    if data.parallel_calls != 1:
        llm = await llm_repo.update(llm, parallel_calls=data.parallel_calls)

    return LLMWithProviderResponse(
        llm=LLMRepository.to_response(llm),
        provider=LLMProviderRepository.to_response(provider),
    )


@router.get("", response_model=list[LLMResponse])
async def get_llms(
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    only_active: bool = Query(False, description="Только активные"),
):
    """
    Получить список LLM моделей пользователя.
    """
    items = await llm_repo.get_by_owner(
        owner_id=current_user.id,
        only_active=only_active,
    )
    return [LLMRepository.to_response(llm) for llm in items]


@router.get("/providers", response_model=list[LLMProviderResponse])
async def get_providers(
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
    only_active: bool = Query(False, description="Только активные"),
):
    """
    Получить список провайдеров пользователя.
    """
    items = await provider_repo.get_by_owner(
        owner_id=current_user.id,
        only_active=only_active,
    )
    return [LLMProviderRepository.to_response(p) for p in items]


@router.get("/providers/types", response_model=list[str])
async def get_provider_types(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Получить список доступных типов провайдеров.
    """
    return [t.value for t in LLMProviderType]


@router.post("/providers/models/fetch", response_model=list[AvailableModel])
async def fetch_available_models(
    data: FetchModelsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Получить список доступных моделей по типу провайдера и настройкам.

    Позволяет получить модели без создания провайдера,
    просто передав тип и настройки подключения.
    """
    # Создаём временный объект провайдера для получения моделей
    temp_provider = LLMProvider(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        type=data.provider_type,
        settings=data.settings.model_dump(exclude_none=True),
    )

    try:
        models = await LLMProviderRepository.fetch_available_models(temp_provider)
    except ModelFetchError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch models from provider '{e.provider_type}': {e.detail}",
        )
    return models


@router.get("/providers/{provider_id}", response_model=LLMProviderResponse)
async def get_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Получить провайдера по ID.
    """
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )
    return LLMProviderRepository.to_response(provider)


@router.get("/providers/{provider_id}/models", response_model=list[AvailableModel])
async def get_available_models_by_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Получить список доступных моделей от провайдера.

    Использует настройки (settings) провайдера для подключения к API
    и получения списка моделей.
    """
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )
    try:
        models = await LLMProviderRepository.fetch_available_models(provider)
    except ModelFetchError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch models from provider '{e.provider_type}': {e.detail}",
        )
    return models


@router.patch("/providers/{provider_id}", response_model=LLMProviderResponse)
async def update_provider(
    provider_id: uuid.UUID,
    data: LLMProviderUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Обновить провайдера.
    """
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )

    update_data = {}
    if data.type is not None:
        update_data["type"] = data.type
    if data.name is not None:
        update_data["name"] = data.name
    if data.settings is not None:
        update_data["settings"] = data.settings.model_dump(exclude_none=True)
    if data.is_active is not None:
        update_data["is_active"] = data.is_active

    if update_data:
        provider = await provider_repo.update(provider, **update_data)

    return LLMProviderRepository.to_response(provider)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Удалить провайдера.

    ВНИМАНИЕ: Каскадно удалит все LLM модели, привязанные к этому провайдеру!
    """
    provider = await get_provider_with_owner_check(
        provider_id, current_user.id, provider_repo
    )
    await provider_repo.delete(provider)


@router.get("/{llm_id}", response_model=LLMWithProviderResponse)
async def get_llm(
    llm_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Получить LLM по ID вместе с информацией о провайдере.
    """
    llm = await get_llm_with_owner_check(llm_id, current_user.id, llm_repo)
    provider = await provider_repo.get_by_id(llm.provider_id)

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    return LLMWithProviderResponse(
        llm=LLMRepository.to_response(llm),
        provider=LLMProviderRepository.to_response(provider),
    )


@router.patch("/{llm_id}", response_model=LLMWithProviderResponse)
async def update_llm_with_provider(
    llm_id: uuid.UUID,
    data: LLMWithProviderUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    provider_repo: Annotated[
        LLMProviderRepository, Depends(get_llm_provider_repository)
    ],
):
    """
    Обновить LLM и/или его провайдера.
    
    Логика работы с провайдером:
    - Если указан provider_id — переключиться на указанный провайдер (и обновить его, если переданы другие поля).
    - Если указан provider_type (без provider_id) — создать нового провайдера и привязать к нему LLM.
    - Если не указаны ни provider_id, ни provider_type — обновить текущий провайдер LLM переданными полями.
    """
    llm = await get_llm_with_owner_check(llm_id, current_user.id, llm_repo)
    
    # Собираем данные для обновления провайдера
    provider_updates = {}
    if data.provider_name is not None:
        provider_updates["name"] = data.provider_name
    if data.provider_settings is not None:
        settings_dict = data.provider_settings.model_dump(exclude_none=True)
        if settings_dict:
            provider_updates["settings"] = settings_dict
    if data.provider_is_active is not None:
        provider_updates["is_active"] = data.provider_is_active
    
    provider_id_changed = False
    
    if data.provider_id:
        # Переключаемся на указанный провайдер
        provider = await get_provider_with_owner_check(
            data.provider_id, current_user.id, provider_repo
        )
        
        # Обновляем тип провайдера если указан
        if data.provider_type is not None:
            provider_updates["type"] = data.provider_type
        
        # Обновляем провайдера если есть изменения
        if provider_updates:
            provider = await provider_repo.update(provider, **provider_updates)
        
        # Проверяем, изменился ли provider_id
        if llm.provider_id != data.provider_id:
            provider_id_changed = True
            
    elif data.provider_type:
        # Создаём нового провайдера
        provider = await provider_repo.create(
            owner_id=current_user.id,
            provider_type=data.provider_type,
            name=data.provider_name,
            settings=(
                data.provider_settings.model_dump(exclude_none=True)
                if data.provider_settings
                else {}
            ),
            is_active=data.provider_is_active if data.provider_is_active is not None else True,
        )
        provider_id_changed = True
    else:
        # Обновляем текущий провайдер LLM
        provider = await provider_repo.get_by_id(llm.provider_id)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider not found",
            )
        
        if provider_updates:
            provider = await provider_repo.update(provider, **provider_updates)

    # Обновляем LLM если переданы данные
    llm_updates = {}
    
    # Обновляем provider_id если он изменился
    if provider_id_changed:
        llm_updates["provider_id"] = provider.id
    
    if data.model_id is not None:
        llm_updates["model_id"] = data.model_id
    if data.llm_name is not None:
        llm_updates["name"] = data.llm_name
    if data.llm_settings is not None:
        llm_updates["settings"] = data.llm_settings.model_dump(exclude_none=True)
    if data.parallel_calls is not None:
        llm_updates["parallel_calls"] = data.parallel_calls
    if data.is_active is not None:
        llm_updates["is_active"] = data.is_active

    if llm_updates:
        llm = await llm_repo.update(llm, **llm_updates)

    return LLMWithProviderResponse(
        llm=LLMRepository.to_response(llm),
        provider=LLMProviderRepository.to_response(provider),
    )


@router.delete("/{llm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm(
    llm_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
):
    """
    Удалить LLM модель.
    """
    llm = await get_llm_with_owner_check(llm_id, current_user.id, llm_repo)
    await llm_repo.delete(llm)
