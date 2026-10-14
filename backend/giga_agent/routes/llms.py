"""API router for LLM records and model discovery."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure runtime registrations
import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401
from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.core.cache import cache
from giga_agent.core.db import get_session
from giga_agent.llm.registry import LLMRegistry
from giga_agent.models import (
    LLM,
    AvailableModel,
    LLMCreate,
    LLMRepository,
    LLMResponse,
    LLMUpdate,
    ModelFetchError,
)
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserShort
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
from giga_agent.routes._shared.schema import (
    build_settings_schema_with_computed_defaults,
)

router = APIRouter(prefix="/llms", tags=["llms"])


class LLMTypeMeta(BaseModel):
    type: str
    supported_connector_types: list[str]


class FetchModelsRequest(BaseModel):
    llm_type: str = Field(..., description="LLM runtime type")
    connector_type: str = Field(..., description="Connector type")
    settings: dict[str, Any] = Field(default_factory=dict)


async def get_llm_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> LLMRepository:
    return LLMRepository(db)


async def get_connector_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectorRepository:
    return ConnectorRepository(db)


async def _get_llm_with_write_check(
    *,
    llm_id: uuid.UUID,
    user_id: uuid.UUID,
    llm_repo: LLMRepository,
) -> LLM:
    return await fetch_resource_with_access_check(
        resource_id=llm_id,
        user_id=user_id,
        repository=llm_repo,
        not_found_detail="LLM not found",
        require_edit=True,
    )


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
        resource_label="llm",
        require_owner=require_owner,
        require_when_supported=True,
    )
    assert validated_connector_id is not None
    return validated_connector_id


def _resolve_llm_runtime(llm_type: str, *, status_code: int) -> type:
    if not LLMRegistry.is_registered(llm_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown llm type: '{llm_type}'. "
                f"Available: {LLMRegistry.available_types()}"
            ),
        )
    return LLMRegistry.get(llm_type)


def _resolve_llm_runtime_by_type(llm_type: str, *, status_code: int) -> type:
    key = (llm_type or "").lower()
    if not LLMRegistry.is_registered(key):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown llm type: '{llm_type}'. "
                f"Available: {LLMRegistry.available_types()}"
            ),
        )
    return LLMRegistry.get(key)


def _validate_llm_connector_compatibility(
    *,
    llm_type: str,
    connector_type: str,
    status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY,
) -> None:
    runtime_cls = _resolve_llm_runtime(llm_type, status_code=status_code)
    if not runtime_cls.is_connector_supported(connector_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"LLM type '{llm_type}' is not compatible with connector type '{connector_type}'. "
                f"Supported connector types: {runtime_cls.supported_connector_types()}"
            ),
        )


async def _check_connection_or_http_error(
    *,
    runtime_cls: type,
    connector_type: str,
    connector_settings: dict[str, Any],
    model_id: str,
    settings: dict[str, Any],
) -> None:
    try:
        connector_runtime = await ConnectorRegistry.get_runtime(
            connector_type,
            connector_settings,
        )
        runtime = runtime_cls(
            connector=connector_runtime,
            model_id=model_id,
            **settings,
        )
        await runtime.check_connection()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"LLM connection check failed: {e}",
        ) from e


@router.get("/types", response_model=list[str])
async def get_llm_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return LLMRegistry.available_types()


@router.get("/types/meta", response_model=list[LLMTypeMeta])
async def get_llm_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return [
        LLMTypeMeta(
            type=item,
            supported_connector_types=LLMRegistry.get(item).supported_connector_types(),
        )
        for item in LLMRegistry.available_types()
    ]


@router.get("/types/{llm_type}/settings-schema", response_model=dict[str, Any])
async def get_llm_settings_schema(
    llm_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_llm_runtime_by_type(
        llm_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return build_settings_schema_with_computed_defaults(runtime_cls.settings_schema())


@router.post("", response_model=LLMResponse, status_code=status.HTTP_201_CREATED)
async def create_llm(
    data: LLMCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    if data.permissions is not None:
        require_superuser(current_user)

    runtime_cls = _resolve_llm_runtime(
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

    _validate_llm_connector_compatibility(
        llm_type=data.type,
        connector_type=connector.type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    raw_settings = data.settings.model_dump(exclude_none=True)
    try:
        validated_settings = await runtime_cls.validate_settings(raw_settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    if data.check_connection:
        await _check_connection_or_http_error(
            runtime_cls=runtime_cls,
            connector_type=connector.type,
            connector_settings=connector.settings or {},
            model_id=data.model_id,
            settings=validated_settings,
        )

    llm = await llm_repo.create(
        owner_id=current_user.id,
        llm_type=data.type,
        connector_id=data.connector_id,
        model_id=data.model_id,
        context_window=data.context_window,
        name=data.name,
        parallel_calls=data.parallel_calls,
        settings=validated_settings,
        is_active=data.is_active,
    )
    if data.permissions is not None:
        await ResourcePermissionRepository(llm_repo.db).set_read_acl(
            resource_type="llm",
            resource_id=llm.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )
    response = LLMRepository.to_response(llm, can_edit=True)
    await cache.delete_tags(f"llms:{current_user.id}")
    return response


@router.get("", response_model=list[LLMResponse])
async def get_llms(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    only_active: bool = Query(False, description="Only active LLMs"),
):
    rows = await llm_repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        LLMRepository.to_response(
            item,
            can_edit=can_edit,
        )
        for item, can_edit in rows
    ]


@router.get("/models/{connector_id}", response_model=list[AvailableModel])
async def get_available_models_by_connector(
    connector_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
    llm_type: str = Query(..., description="LLM runtime type"),
):
    runtime_cls = _resolve_llm_runtime_by_type(
        llm_type,
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

    _validate_llm_connector_compatibility(
        llm_type=llm_type,
        connector_type=connector.type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return await fetch_models_from_connector_or_http_error(
        runtime_cls=runtime_cls,
        connector=connector,
        fetch_error_type=ModelFetchError,
        failure_message_builder=lambda e: (
            f"Failed to fetch models from llm '{e.llm_type}': {e.detail}"
        ),
        get_runtime=ConnectorRegistry.get_runtime,
        runtime_type=llm_type,
    )


@router.post("/models/", response_model=list[AvailableModel])
async def fetch_available_models(
    data: FetchModelsRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    normalized_settings = await validate_connector_settings_or_422(
        data.connector_type,
        data.settings,
    )

    _validate_llm_connector_compatibility(
        llm_type=data.llm_type,
        connector_type=data.connector_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    runtime_cls = _resolve_llm_runtime_by_type(
        data.llm_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )

    return await fetch_models_or_http_error(
        runtime_cls=runtime_cls,
        connector_type=data.connector_type,
        connector_settings=normalized_settings,
        fetch_error_type=ModelFetchError,
        failure_message_builder=lambda e: (
            f"Failed to fetch models from llm '{e.llm_type}': {e.detail}"
        ),
        get_runtime=ConnectorRegistry.get_runtime,
        runtime_type=data.llm_type,
    )


@router.get("/{llm_id}", response_model=LLMResponse)
async def get_llm(
    llm_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
):
    llm, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=llm_id,
        user_id=current_user.id,
        repository=llm_repo,
        not_found_detail="LLM not found",
    )
    return LLMRepository.to_response(llm, can_edit=can_edit)


@router.patch("/{llm_id}", response_model=LLMResponse)
async def patch_llm(
    llm_id: uuid.UUID,
    data: LLMUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    llm = await _get_llm_with_write_check(
        llm_id=llm_id,
        user_id=current_user.id,
        llm_repo=llm_repo,
    )

    effective_type = (
        data.type
        if "type" in data.model_fields_set and data.type is not None
        else llm.type
    )
    effective_connector_id = (
        data.connector_id
        if "connector_id" in data.model_fields_set and data.connector_id is not None
        else llm.connector_id
    )
    effective_model_id = (
        data.model_id
        if "model_id" in data.model_fields_set and data.model_id is not None
        else llm.model_id
    )

    runtime_cls = _resolve_llm_runtime(
        effective_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    validated_connector_id = await _validate_connector_link(
        user_id=current_user.id,
        connector_id=effective_connector_id,
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

    _validate_llm_connector_compatibility(
        llm_type=effective_type,
        connector_type=connector.type,
    )

    update_data: dict[str, Any] = {}
    effective_settings = llm.settings or {}

    if "type" in data.model_fields_set:
        if data.type is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="type must not be null when provided",
            )
        update_data["type"] = data.type

    if "connector_id" in data.model_fields_set:
        if data.connector_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="connector_id must not be null when provided",
            )
        update_data["connector_id"] = data.connector_id

    if "model_id" in data.model_fields_set:
        if data.model_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="model_id must not be null when provided",
            )
        update_data["model_id"] = data.model_id

    if "name" in data.model_fields_set:
        update_data["name"] = data.name

    if "context_window" in data.model_fields_set:
        update_data["context_window"] = data.context_window

    if "parallel_calls" in data.model_fields_set:
        if data.parallel_calls is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="parallel_calls must not be null when provided",
            )
        update_data["parallel_calls"] = data.parallel_calls

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
        raw_settings = data.settings.model_dump(exclude_none=True)
        try:
            effective_settings = await runtime_cls.validate_settings(raw_settings)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        update_data["settings"] = effective_settings

    if data.check_connection:
        await _check_connection_or_http_error(
            runtime_cls=runtime_cls,
            connector_type=connector.type,
            connector_settings=connector.settings or {},
            model_id=effective_model_id,
            settings=effective_settings,
        )

    if update_data:
        llm = await llm_repo.update(llm, **update_data)

    response = LLMRepository.to_response(llm, can_edit=True)
    await cache.delete_tags(f"llms:{current_user.id}")
    await cache.delete_tags(f"llm:{llm_id}")
    return response


@router.delete("/{llm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm(
    llm_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    llm_repo: Annotated[LLMRepository, Depends(get_llm_repository)],
):
    llm = await _get_llm_with_write_check(
        llm_id=llm_id,
        user_id=current_user.id,
        llm_repo=llm_repo,
    )
    await llm_repo.delete(llm)
