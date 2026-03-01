"""API router for connector management."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.core.db import get_session
from giga_agent.embeddings.registry import EmbeddingRegistry
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.llm.registry import LLMRegistry
from giga_agent.models.connector import (
    Connector,
    ConnectorCreate,
    ConnectorRepository,
    ConnectorResponse,
    ConnectorUpdate,
)
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)
from giga_agent.search_engines.registry import SearchEngineRegistry

# Ensure runtime registrations
import giga_agent.connectors  # noqa: F401
import giga_agent.embeddings  # noqa: F401
import giga_agent.generators.image  # noqa: F401
import giga_agent.llm  # noqa: F401
import giga_agent.search_engines  # noqa: F401

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ConnectorTypeMeta(BaseModel):
    type: str


async def get_connector_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectorRepository:
    return ConnectorRepository(db)


async def get_llm_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> LLMRepository:
    return LLMRepository(db)


async def get_image_generator_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ImageGeneratorRepository:
    return ImageGeneratorRepository(db)


async def get_embedding_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EmbeddingRepository:
    return EmbeddingRepository(db)


async def get_search_engine_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SearchEngineRepository:
    return SearchEngineRepository(db)


def _resolve_runtime_cls(connector_type: str, *, status_code: int) -> type:
    if not ConnectorRegistry.is_registered(connector_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown connector type: '{connector_type}'. "
                f"Available: {ConnectorRegistry.available_types()}"
            ),
        )
    return ConnectorRegistry.get(connector_type)


async def _validate_settings(
    connector_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
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


async def _get_connector_with_read_check(
    *,
    connector_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_repo: ConnectorRepository,
) -> Connector:
    return await fetch_resource_with_access_check(
        resource_id=connector_id,
        user_id=user_id,
        repository=connector_repo,
        not_found_detail="Connector not found",
    )


async def _get_connector_with_write_check(
    *,
    connector_id: uuid.UUID,
    user_id: uuid.UUID,
    connector_repo: ConnectorRepository,
) -> Connector:
    return await fetch_resource_with_access_check(
        resource_id=connector_id,
        user_id=user_id,
        repository=connector_repo,
        not_found_detail="Connector not found",
        require_edit=True,
    )


async def _validate_type_change_compatibility(
    *,
    connector_id: uuid.UUID,
    connector_type: str,
    llm_repo: LLMRepository,
    embedding_repo: EmbeddingRepository,
    image_repo: ImageGeneratorRepository,
    search_repo: SearchEngineRepository,
) -> None:
    llms = await llm_repo.get_by_connector(connector_id, only_active=False)
    embeddings = await embedding_repo.get_by_connector(connector_id, only_active=False)
    generators = await image_repo.get_by_connector(connector_id, only_active=False)
    engines = await search_repo.get_by_connector(connector_id, only_active=False)

    normalized_type = (connector_type or "").lower()

    for llm in llms:
        try:
            runtime_cls = LLMRegistry.get(llm.type)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        if not runtime_cls.is_connector_supported(normalized_type):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Connector type '{normalized_type}' is not compatible with LLM '{llm.id}' "
                    f"(type '{llm.type}'). Supported connector types: "
                    f"{runtime_cls.supported_connector_types()}"
                ),
            )

    for generator in generators:
        try:
            runtime_cls = ImageGeneratorRegistry.get(generator.type)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        supported = [item.lower() for item in runtime_cls.supported_connector_types()]
        if normalized_type not in supported:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Connector type '{normalized_type}' is not compatible with image generator "
                    f"'{generator.id}' (type '{generator.type}'). Supported connector types: {supported}"
                ),
            )

    for embedding in embeddings:
        try:
            runtime_cls = EmbeddingRegistry.get(embedding.type)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        if not runtime_cls.is_connector_supported(normalized_type):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Connector type '{normalized_type}' is not compatible with embedding "
                    f"'{embedding.id}' (type '{embedding.type}'). Supported connector types: "
                    f"{runtime_cls.supported_connector_types()}"
                ),
            )

    for engine in engines:
        try:
            runtime_cls = SearchEngineRegistry.get(engine.type)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        supported = [item.lower() for item in runtime_cls.supported_connector_types()]
        if normalized_type not in supported:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Connector type '{normalized_type}' is not compatible with search engine "
                    f"'{engine.id}' (type '{engine.type}'). Supported connector types: {supported}"
                ),
            )


@router.get("/types", response_model=list[str])
async def get_connector_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return ConnectorRegistry.available_types()


@router.get("/types/meta", response_model=list[ConnectorTypeMeta])
async def get_connector_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return [
        ConnectorTypeMeta(type=connector_type)
        for connector_type in ConnectorRegistry.available_types()
    ]


@router.get("/types/{connector_type}/settings-schema", response_model=dict[str, Any])
async def get_connector_settings_schema(
    connector_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_runtime_cls(
        connector_type,
        status_code=status.HTTP_404_NOT_FOUND,
    )
    return runtime_cls.settings_schema().model_json_schema()


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def create_connector(
    data: ConnectorCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    if data.permissions is not None:
        require_superuser(current_user)

    _resolve_runtime_cls(data.type, status_code=status.HTTP_400_BAD_REQUEST)
    validated_settings = await _validate_settings(data.type, data.settings)

    connector = await connector_repo.create(
        owner_id=current_user.id,
        connector_type=data.type,
        name=data.name,
        settings=validated_settings,
        is_active=data.is_active,
    )
    if data.permissions is not None:
        await ResourcePermissionRepository(connector_repo.db).set_read_acl(
            resource_type="connector",
            resource_id=connector.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )
    return ConnectorRepository.to_response(connector, can_edit=True)


@router.get("", response_model=list[ConnectorResponse])
async def get_connectors(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
    only_active: bool = Query(False, description="Only active connectors"),
):
    rows = await connector_repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        ConnectorRepository.to_response(
            item,
            can_edit=can_edit,
        )
        for item, can_edit in rows
    ]


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    connector, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=connector_id,
        user_id=current_user.id,
        repository=connector_repo,
        not_found_detail="Connector not found",
    )
    return ConnectorRepository.to_response(connector, can_edit=can_edit)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def patch_connector(
    connector_id: uuid.UUID,
    data: ConnectorUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    embedding_repo: Annotated[EmbeddingRepository, Depends(get_embedding_repository)],
    image_repo: Annotated[
        ImageGeneratorRepository, Depends(get_image_generator_repository)
    ],
    search_repo: Annotated[
        SearchEngineRepository, Depends(get_search_engine_repository)
    ],
):
    connector = await _get_connector_with_write_check(
        connector_id=connector_id,
        user_id=current_user.id,
        connector_repo=connector_repo,
    )

    update_data: dict[str, Any] = {}
    effective_type = connector.type

    if "name" in data.model_fields_set:
        update_data["name"] = data.name

    if "is_active" in data.model_fields_set:
        update_data["is_active"] = data.is_active

    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        update_data["settings"] = await _validate_settings(
            effective_type, data.settings
        )
    elif "type" in data.model_fields_set:
        # If type changed and settings were not passed, revalidate existing settings with new runtime.
        update_data["settings"] = await _validate_settings(
            effective_type, connector.settings or {}
        )

    if "type" in data.model_fields_set and effective_type != connector.type:
        await _validate_type_change_compatibility(
            connector_id=connector.id,
            connector_type=effective_type,
            llm_repo=llm_repo,
            embedding_repo=embedding_repo,
            image_repo=image_repo,
            search_repo=search_repo,
        )

    if update_data:
        connector = await connector_repo.update(connector, **update_data)

    return ConnectorRepository.to_response(connector, can_edit=True)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    connector = await _get_connector_with_write_check(
        connector_id=connector_id,
        user_id=current_user.id,
        connector_repo=connector_repo,
    )

    await connector_repo.delete(connector)
