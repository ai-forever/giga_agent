"""API router for embeddings records and model discovery."""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
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
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.core.events import event_bus
from giga_agent.modules.auth.events import UserEmbeddingChangedEvent
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)
from giga_agent.routes._shared.connectors import validate_connector_link
from giga_agent.routes._shared.model_discovery import (
    fetch_models_from_connector_or_http_error,
    fetch_models_or_http_error,
    validate_connector_settings_or_422,
)
from giga_agent.routes._shared.users import (
    clear_user_current_link_if_matches,
    get_user_model,
)

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


async def _check_connection_or_http_error(
    *,
    runtime_cls: type,
    connector: Connector,
    model_id: str,
    embedding_settings: dict[str, Any],
) -> None:
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
        runtime = runtime_cls(
            connector=connector_runtime,
            model_id=model_id,
            vector_size=1,
            **embedding_settings,
        )
        await runtime.check_connection()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Embedding connection check failed: {e}",
        ) from e


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


async def _validate_connector_link(
    *,
    user_id: uuid.UUID,
    connector_id: uuid.UUID,
    supported_connector_types: list[str],
    connector_repo: ConnectorRepository,
    require_owner: bool = False,
) -> uuid.UUID:
    validated_connector_id = await validate_connector_link(
        user_id=user_id,
        connector_id=connector_id,
        supported_connector_types=supported_connector_types,
        connector_repo=connector_repo,
        resource_label="embedding",
        require_owner=require_owner,
        require_when_supported=True,
    )
    assert validated_connector_id is not None
    return validated_connector_id


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


async def _get_embedding_with_write_check(
    *,
    embedding_id: uuid.UUID,
    user_id: uuid.UUID,
    embedding_repo: EmbeddingRepository,
) -> Embedding:
    return await fetch_resource_with_access_check(
        resource_id=embedding_id,
        user_id=user_id,
        repository=embedding_repo,
        not_found_detail="Embedding not found",
        require_edit=True,
    )


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
    db: Annotated[AsyncSession, Depends(get_session)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    if data.permissions is not None:
        require_superuser(current_user)

    runtime_cls = _resolve_embedding_runtime(
        data.type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    validated_connector_id = await _validate_connector_link(
        user_id=current_user.id,
        connector_id=data.connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
    )
    connector = await connector_repo.get_by_id(validated_connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
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
    if data.check_connection:
        await _check_connection_or_http_error(
            runtime_cls=runtime_cls,
            connector=connector,
            model_id=data.model_id,
            embedding_settings=validated_settings,
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
    if data.permissions is not None:
        await ResourcePermissionRepository(embedding_repo.db).set_read_acl(
            resource_type="embedding",
            resource_id=embedding.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )

    user = await get_user_model(db=db, owner_id=current_user.id)
    old_embedding_id = user.embedding_id
    if user.embedding_id is None:
        user.embedding_id = embedding.id
        await db.commit()
        await db.refresh(user)
        await UserRepository.invalidate_cache(current_user.id)
        await event_bus.publish(
            UserEmbeddingChangedEvent(
                user_id=current_user.id,
                old_embedding_id=old_embedding_id,
                new_embedding_id=user.embedding_id,
            )
        )

    return EmbeddingRepository.to_response(embedding, can_edit=True)


@router.get("", response_model=list[EmbeddingResponse])
async def get_embeddings(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
    only_active: bool = Query(False, description="Only active embeddings"),
):
    rows = await embedding_repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        EmbeddingRepository.to_response(
            item,
            can_edit=can_edit,
        )
        for item, can_edit in rows
    ]


@router.get("/models/{connector_id}", response_model=list[AvailableEmbeddingModel])
async def get_available_models_by_connector(
    connector_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
    embedding_type: str = Query(..., description="Embedding runtime type"),
):
    runtime_cls = _resolve_embedding_runtime_by_type(
        embedding_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    validated_connector_id = await _validate_connector_link(
        user_id=current_user.id,
        connector_id=connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
    )
    connector = await connector_repo.get_by_id(validated_connector_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
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
    return await fetch_models_from_connector_or_http_error(
        runtime_cls=runtime_cls,
        connector=connector,
        fetch_error_type=EmbeddingModelFetchError,
        failure_message_builder=lambda e: (
            f"Failed to fetch models from embeddings '{e.embedding_type}': "
            f"{e.detail}"
        ),
        connector_runtime_error_message="Некорректные настройки коннектора для эмбеддингов",
        get_runtime=ConnectorRegistry.get_runtime,
    )


@router.post("/models/", response_model=list[AvailableEmbeddingModel])
async def fetch_available_models(
    data: FetchModelsRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    normalized_settings = await validate_connector_settings_or_422(
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

    return await fetch_models_or_http_error(
        runtime_cls=runtime_cls,
        connector_type=data.connector_type,
        connector_settings=normalized_settings,
        fetch_error_type=EmbeddingModelFetchError,
        failure_message_builder=lambda e: (
            f"Failed to fetch models from embeddings '{e.embedding_type}': "
            f"{e.detail}"
        ),
        connector_runtime_error_message="Некорректные настройки коннектора для эмбеддингов",
        get_runtime=ConnectorRegistry.get_runtime,
    )


@router.get("/{embedding_id}", response_model=EmbeddingResponse)
async def get_embedding(
    embedding_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
):
    embedding, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=embedding_id,
        user_id=current_user.id,
        repository=embedding_repo,
        not_found_detail="Embedding not found",
    )
    return EmbeddingRepository.to_response(embedding, can_edit=can_edit)


@router.delete("/{embedding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_embedding(
    embedding_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
):
    user = await get_user_model(db=db, owner_id=current_user.id)
    embedding = await _get_embedding_with_write_check(
        embedding_id=embedding_id,
        user_id=current_user.id,
        embedding_repo=embedding_repo,
    )
    old_embedding_id = (
        user.embedding_id if user.embedding_id == embedding.id else None
    )
    await embedding_repo.delete(embedding)
    was_cleared = await clear_user_current_link_if_matches(
        db=db,
        owner_id=current_user.id,
        resource_id=embedding.id,
        user_field_name="embedding_id",
    )
    if was_cleared and old_embedding_id is not None:
        await event_bus.publish(
            UserEmbeddingChangedEvent(
                user_id=current_user.id,
                old_embedding_id=old_embedding_id,
                new_embedding_id=None,
            )
        )
