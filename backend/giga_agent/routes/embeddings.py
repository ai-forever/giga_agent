"""API router for embeddings records and model discovery."""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.core.db import get_session
from giga_agent.embeddings.registry import EmbeddingRegistry
from giga_agent.models.connector import Connector, ConnectorRepository
from giga_agent.models.embedding import (
    AvailableEmbeddingModel,
    Embedding,
    EmbeddingCreate,
    EmbeddingModelFetchError,
    EmbeddingRepository,
    EmbeddingResponse,
)
from giga_agent.models.users import User, UserRepository, UserShort
from giga_agent.modules.auth.api import get_current_active_user

# Ensure runtime registrations
import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class EmbeddingTypeMeta(BaseModel):
    type: str
    supported_connector_types: list[str]


class FetchModelsRequest(BaseModel):
    embedding_type: str
    connector_type: str
    settings: dict[str, Any] = Field(default_factory=dict)


async def get_embedding_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EmbeddingRepository:
    return EmbeddingRepository(db)


async def get_connector_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectorRepository:
    return ConnectorRepository(db)


def _resolve_embedding_runtime(embedding_type: str, *, status_code: int) -> type:
    if not EmbeddingRegistry.is_registered(embedding_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown embedding type: '{embedding_type}'. "
                f"Available: {EmbeddingRegistry.available_types()}"
            ),
        )
    return EmbeddingRegistry.get(embedding_type)


def _resolve_embedding_runtime_by_type(
    embedding_type: str,
    *,
    status_code: int,
) -> type:
    key = (embedding_type or "").lower()
    if not EmbeddingRegistry.is_registered(key):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown embedding type: '{embedding_type}'. "
                f"Available: {EmbeddingRegistry.available_types()}"
            ),
        )
    return EmbeddingRegistry.get(key)


async def _validate_connector_settings(
    connector_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    if not ConnectorRegistry.is_registered(connector_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown connector type: '{connector_type}'. "
                f"Available: {ConnectorRegistry.available_types()}"
            ),
        )

    try:
        return await ConnectorRegistry.validate_settings(connector_type, settings)
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


async def _validate_settings(
    embedding_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await EmbeddingRegistry.validate_settings(embedding_type, settings)
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


async def _probe_embedding_vector_size(
    *,
    embedding_type: str,
    model_id: str,
    connector: Connector,
    embedding_settings: dict[str, Any],
) -> int:
    runtime_cls = _resolve_embedding_runtime(
        embedding_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    try:
        connector_runtime = await ConnectorRegistry.get_runtime(
            connector.type,
            connector.settings or {},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Некорректные настройки коннектора для эмбеддингов",
        ) from e

    runtime = runtime_cls(
        connector=connector_runtime,
        model_id=model_id,
        vector_size=1,
        **embedding_settings,
    )
    embeddings = runtime.embeddings

    try:
        if hasattr(embeddings, "aembed_query"):
            vector = await embeddings.aembed_query("vector size probe")
        else:
            vector = await asyncio.to_thread(embeddings.embed_query, "vector size probe")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Невозможно подключиться к эмбеддингам. "
                "Проверьте коннектор и название модели."
            ),
        ) from e

    if not isinstance(vector, list) or not vector:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Эмбеддинги вернули некорректный вектор. "
                "Проверьте коннектор и название модели."
            ),
        )

    vector_size = len(vector)
    if vector_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Эмбеддинги вернули некорректный размер вектора. "
                "Проверьте коннектор и название модели."
            ),
        )

    return vector_size


async def _get_connector_with_owner_check(
    *,
    connector_id: uuid.UUID,
    owner_id: uuid.UUID,
    connector_repo: ConnectorRepository,
) -> Connector:
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
    return connector


def _validate_embedding_connector_compatibility(
    *,
    embedding_type: str,
    connector_type: str,
    status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY,
) -> None:
    runtime_cls = _resolve_embedding_runtime(embedding_type, status_code=status_code)
    if not runtime_cls.is_connector_supported(connector_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Embedding type '{embedding_type}' is not compatible with connector type "
                f"'{connector_type}'. Supported connector types: "
                f"{runtime_cls.supported_connector_types()}"
            ),
        )


async def _get_embedding_with_owner_check(
    *,
    embedding_id: uuid.UUID,
    owner_id: uuid.UUID,
    embedding_repo: EmbeddingRepository,
) -> Embedding:
    embedding = await embedding_repo.get_by_id(embedding_id)
    if embedding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embedding not found",
        )
    if embedding.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return embedding


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
    embedding_id: uuid.UUID,
) -> bool:
    user = await _get_user_model(db=db, owner_id=owner_id)
    if user.embedding_id != embedding_id:
        return False

    user.embedding_id = None
    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(owner_id)
    return True


@router.get("/types", response_model=list[str])
async def get_embedding_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return EmbeddingRegistry.available_types()


@router.get("/types/meta", response_model=list[EmbeddingTypeMeta])
async def get_embedding_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return [
        EmbeddingTypeMeta(
            type=item,
            supported_connector_types=EmbeddingRegistry.get(item).supported_connector_types(),
        )
        for item in EmbeddingRegistry.available_types()
    ]


@router.get("/types/{embedding_type}/settings-schema", response_model=dict[str, Any])
async def get_embedding_settings_schema(
    embedding_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_embedding_runtime(
        embedding_type,
        status_code=status.HTTP_404_NOT_FOUND,
    )
    return runtime_cls.settings_schema().model_json_schema()


@router.post("", response_model=EmbeddingResponse, status_code=status.HTTP_201_CREATED)
async def create_embedding(
    data: EmbeddingCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    connector = await _get_connector_with_owner_check(
        connector_id=data.connector_id,
        owner_id=current_user.id,
        connector_repo=connector_repo,
    )
    if not connector.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector must be active",
        )

    _validate_embedding_connector_compatibility(
        embedding_type=data.type,
        connector_type=connector.type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    validated_settings = await _validate_settings(
        data.type,
        data.settings or {},
    )

    vector_size = await _probe_embedding_vector_size(
        embedding_type=data.type,
        model_id=data.model_id,
        connector=connector,
        embedding_settings=validated_settings,
    )

    embedding = await embedding_repo.create(
        owner_id=current_user.id,
        embedding_type=data.type,
        connector_id=data.connector_id,
        model_id=data.model_id,
        name=data.name,
        vector_size=vector_size,
        settings=validated_settings,
        is_active=data.is_active,
    )
    return EmbeddingRepository.to_response(embedding)


@router.get("", response_model=list[EmbeddingResponse])
async def get_embeddings(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
    only_active: bool = Query(False, description="Only active embeddings"),
):
    items = await embedding_repo.get_by_owner(current_user.id, only_active=only_active)
    return [EmbeddingRepository.to_response(item) for item in items]


@router.get("/models/{connector_id}", response_model=list[AvailableEmbeddingModel])
async def get_available_models_by_connector(
    connector_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
    embedding_type: str = Query(..., description="Embedding runtime type"),
):
    connector = await _get_connector_with_owner_check(
        connector_id=connector_id,
        owner_id=current_user.id,
        connector_repo=connector_repo,
    )
    if not connector.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector must be active",
        )

    _validate_embedding_connector_compatibility(
        embedding_type=embedding_type,
        connector_type=connector.type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    runtime_cls = _resolve_embedding_runtime_by_type(
        embedding_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    try:
        connector_runtime = await ConnectorRegistry.get_runtime(
            connector.type,
            connector.settings or {},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Некорректные настройки коннектора для эмбеддингов",
        ) from e

    try:
        return await runtime_cls.fetch_available_models(
            connector=connector_runtime,
        )
    except EmbeddingModelFetchError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Failed to fetch models from embeddings '{e.embedding_type}': "
                f"{e.detail}"
            ),
        )


@router.post("/models/", response_model=list[AvailableEmbeddingModel])
async def fetch_available_models(
    data: FetchModelsRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    normalized_settings = await _validate_connector_settings(
        data.connector_type,
        data.settings,
    )

    _validate_embedding_connector_compatibility(
        embedding_type=data.embedding_type,
        connector_type=data.connector_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    runtime_cls = _resolve_embedding_runtime_by_type(
        data.embedding_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    try:
        connector_runtime = await ConnectorRegistry.get_runtime(
            data.connector_type,
            normalized_settings,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Некорректные настройки коннектора для эмбеддингов",
        ) from e

    try:
        return await runtime_cls.fetch_available_models(
            connector=connector_runtime,
        )
    except EmbeddingModelFetchError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Failed to fetch models from embeddings '{e.embedding_type}': "
                f"{e.detail}"
            ),
        )


@router.get("/{embedding_id}", response_model=EmbeddingResponse)
async def get_embedding(
    embedding_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
):
    embedding = await _get_embedding_with_owner_check(
        embedding_id=embedding_id,
        owner_id=current_user.id,
        embedding_repo=embedding_repo,
    )
    return EmbeddingRepository.to_response(embedding)


@router.delete("/{embedding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_embedding(
    embedding_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
):
    embedding = await _get_embedding_with_owner_check(
        embedding_id=embedding_id,
        owner_id=current_user.id,
        embedding_repo=embedding_repo,
    )
    await embedding_repo.delete(embedding)
    await _clear_current_if_matches(
        db=db,
        owner_id=current_user.id,
        embedding_id=embedding.id,
    )
