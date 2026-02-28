"""API router for search engine management."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.search_engine import (
    SearchEngine,
    SearchEngineCreate,
    SearchEngineRepository,
    SearchEngineResponse,
)
from giga_agent.models.users import User, UserRepository, UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.search_engines.registry import SearchEngineRegistry

# Ensure providers are registered.
import giga_agent.search_engines  # noqa: F401

router = APIRouter(prefix="/search-engines", tags=["search-engines"])


class SearchEnginePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    settings: dict[str, Any] | None = None
    connector_id: uuid.UUID | None = None
    is_active: bool | None = None


class SearchEngineTypeMeta(BaseModel):
    type: str
    supported_connector_types: list[str]
    requires_connector: bool = False


async def get_search_engine_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SearchEngineRepository:
    return SearchEngineRepository(db)


async def get_connector_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectorRepository:
    return ConnectorRepository(db)


def _resolve_runtime_cls(
    engine_type: str,
    *,
    status_code: int,
) -> type:
    if not SearchEngineRegistry.is_registered(engine_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown search engine type: '{engine_type}'. "
                f"Available: {SearchEngineRegistry.available_types()}"
            ),
        )
    return SearchEngineRegistry.get(engine_type)


async def _validate_settings(
    engine_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await SearchEngineRegistry.validate_settings(engine_type, settings)
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


async def _validate_connector_link(
    *,
    owner_id: uuid.UUID,
    connector_id: uuid.UUID | None,
    supported_connector_types: list[str],
    connector_repo: ConnectorRepository,
) -> uuid.UUID | None:
    normalized_supported = [t.lower() for t in supported_connector_types]

    if not normalized_supported:
        if connector_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This search engine type does not support connector_id.",
            )
        return None

    if connector_id is None:
        return None

    connector = await connector_repo.get_by_id(connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    if connector.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if not connector.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector must be active",
        )

    connector_type = (connector.type or "").lower()
    if connector_type not in normalized_supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Connector type '{connector_type}' is not supported by this "
                f"search engine. Supported: {normalized_supported}"
            ),
        )

    return connector_id


async def _get_engine_with_owner_check(
    *,
    engine_id: uuid.UUID,
    owner_id: uuid.UUID,
    engine_repo: SearchEngineRepository,
) -> SearchEngine:
    engine = await engine_repo.get_by_id(engine_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search engine not found",
        )
    if engine.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return engine


async def _get_engine_with_read_check(
    *,
    engine_id: uuid.UUID,
    user_id: uuid.UUID,
    engine_repo: SearchEngineRepository,
) -> SearchEngine:
    engine = await engine_repo.get_by_id(engine_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search engine not found",
        )
    readable_engine = await engine_repo.get_by_id_readable(
        engine_id,
        user_id=user_id,
    )
    if readable_engine is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return readable_engine


async def _get_user_model(
    *,
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> User:
    result = await db.execute(select(User).where(User.id == owner_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


async def _clear_current_if_matches(
    *,
    db: AsyncSession,
    owner_id: uuid.UUID,
    search_engine_id: uuid.UUID,
) -> bool:
    user = await _get_user_model(db=db, owner_id=owner_id)
    if user.search_engine_id != search_engine_id:
        return False

    user.search_engine_id = None
    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(owner_id)
    return True


@router.get("/types", response_model=list[str])
async def get_engine_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return SearchEngineRegistry.available_types()


@router.get("/types/meta", response_model=list[SearchEngineTypeMeta])
async def get_engine_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return [
        SearchEngineTypeMeta(
            type=engine_type,
            supported_connector_types=[
                t.lower() for t in SearchEngineRegistry.get(engine_type).supported_connector_types()
            ],
            requires_connector=False,
        )
        for engine_type in SearchEngineRegistry.available_types()
    ]


@router.get("/types/{engine_type}/settings-schema", response_model=dict[str, Any])
async def get_engine_settings_schema(
    engine_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_runtime_cls(engine_type, status_code=status.HTTP_404_NOT_FOUND)
    return runtime_cls.settings_schema().model_json_schema()


@router.post("", response_model=SearchEngineResponse, status_code=status.HTTP_201_CREATED)
async def create_search_engine(
    data: SearchEngineCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    engine_repo: Annotated[SearchEngineRepository, Depends(get_search_engine_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    runtime_cls = _resolve_runtime_cls(data.type, status_code=status.HTTP_400_BAD_REQUEST)
    validated_settings = await _validate_settings(data.type, data.settings)
    validated_connector_id = await _validate_connector_link(
        owner_id=current_user.id,
        connector_id=data.connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
    )

    engine = await engine_repo.create(
        owner_id=current_user.id,
        engine_type=data.type,
        name=data.name,
        settings=validated_settings,
        connector_id=validated_connector_id,
        is_active=data.is_active,
    )
    return SearchEngineRepository.to_response(engine)


@router.get("", response_model=list[SearchEngineResponse])
async def get_search_engines(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    engine_repo: Annotated[SearchEngineRepository, Depends(get_search_engine_repository)],
    only_active: bool = Query(False, description="Only active search engines"),
):
    engines = await engine_repo.get_readable_for_user(
        current_user.id,
        only_active=only_active,
    )
    return [SearchEngineRepository.to_response(engine) for engine in engines]


@router.get("/{engine_id}", response_model=SearchEngineResponse)
async def get_search_engine(
    engine_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    engine_repo: Annotated[SearchEngineRepository, Depends(get_search_engine_repository)],
):
    engine = await _get_engine_with_read_check(
        engine_id=engine_id,
        user_id=current_user.id,
        engine_repo=engine_repo,
    )
    return SearchEngineRepository.to_response(engine)


@router.patch("/{engine_id}", response_model=SearchEngineResponse)
async def patch_search_engine(
    engine_id: uuid.UUID,
    data: SearchEnginePatchRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    engine_repo: Annotated[SearchEngineRepository, Depends(get_search_engine_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    engine = await _get_engine_with_owner_check(
        engine_id=engine_id,
        owner_id=current_user.id,
        engine_repo=engine_repo,
    )

    runtime_cls = _resolve_runtime_cls(engine.type, status_code=status.HTTP_400_BAD_REQUEST)
    update_data: dict[str, Any] = {}

    if "name" in data.model_fields_set:
        update_data["name"] = data.name

    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        update_data["settings"] = await _validate_settings(engine.type, data.settings)

    effective_connector_id = (
        data.connector_id
        if "connector_id" in data.model_fields_set
        else engine.connector_id
    )
    validated_connector_id = await _validate_connector_link(
        owner_id=current_user.id,
        connector_id=effective_connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
    )
    if "connector_id" in data.model_fields_set:
        update_data["connector_id"] = validated_connector_id

    is_deactivating_current = False
    if "is_active" in data.model_fields_set:
        update_data["is_active"] = data.is_active
        is_deactivating_current = data.is_active is False

    if update_data:
        engine = await engine_repo.update(engine, **update_data)

    if is_deactivating_current:
        await _clear_current_if_matches(
            db=db,
            owner_id=current_user.id,
            search_engine_id=engine.id,
        )

    return SearchEngineRepository.to_response(engine)


@router.delete("/{engine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_engine(
    engine_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    engine_repo: Annotated[SearchEngineRepository, Depends(get_search_engine_repository)],
):
    engine = await _get_engine_with_owner_check(
        engine_id=engine_id,
        owner_id=current_user.id,
        engine_repo=engine_repo,
    )
    await engine_repo.delete(engine)
    await _clear_current_if_matches(
        db=db,
        owner_id=current_user.id,
        search_engine_id=engine.id,
    )
