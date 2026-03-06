"""API router for image generators."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.core.db import get_session
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.image_generator import (
    ImageGenerator,
    ImageGeneratorCreate,
    ImageGeneratorRepository,
    ImageGeneratorResponse,
)
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)
from giga_agent.routes._shared.connectors import validate_connector_link
from giga_agent.routes._shared.users import (
    clear_user_current_link_if_matches,
)

router = APIRouter(prefix="/image", tags=["generators"])


class ImageGeneratorPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    settings: dict[str, Any] | None = None
    connector_id: uuid.UUID | None = None
    is_active: bool | None = None
    check_connection: bool = True


class ImageGeneratorTypeMeta(BaseModel):
    type: str
    supported_connector_types: list[str]
    requires_connector: bool


async def get_image_generator_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ImageGeneratorRepository:
    return ImageGeneratorRepository(db)


async def get_connector_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ConnectorRepository:
    return ConnectorRepository(db)


def _resolve_runtime_cls(
    generator_type: str,
    *,
    status_code: int,
) -> type:
    if not ImageGeneratorRegistry.is_registered(generator_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown image generator type: '{generator_type}'. "
                f"Available: {ImageGeneratorRegistry.available_types()}"
            ),
        )
    return ImageGeneratorRegistry.get(generator_type)


async def _validate_settings(
    generator_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await ImageGeneratorRegistry.validate_settings(generator_type, settings)
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
    user_id: uuid.UUID,
    connector_id: uuid.UUID | None,
    supported_connector_types: list[str],
    connector_repo: ConnectorRepository,
    require_owner: bool = True,
) -> uuid.UUID | None:
    return await validate_connector_link(
        user_id=user_id,
        connector_id=connector_id,
        supported_connector_types=supported_connector_types,
        connector_repo=connector_repo,
        resource_label="image generator",
        require_owner=require_owner,
        require_when_supported=True,
    )


async def _get_generator_with_write_check(
    *,
    generator_id: uuid.UUID,
    user_id: uuid.UUID,
    generator_repo: ImageGeneratorRepository,
) -> ImageGenerator:
    return await fetch_resource_with_access_check(
        resource_id=generator_id,
        user_id=user_id,
        repository=generator_repo,
        not_found_detail="Image generator not found",
        require_edit=True,
    )


async def _check_connection_or_http_error(
    *,
    runtime_cls: type,
    settings: dict[str, Any],
    connector_id: uuid.UUID | None,
    connector_repo: ConnectorRepository,
) -> None:
    connector_runtime = None
    if connector_id is not None:
        connector = await connector_repo.get_by_id(connector_id)
        if connector is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connector not found",
            )
        try:
            connector_runtime = await ConnectorRegistry.get_runtime(
                connector.type,
                connector.settings or {},
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Image generator connection check failed: {e}",
            ) from e

    try:
        runtime = runtime_cls(**settings, connector=connector_runtime)
        await runtime.check_connection()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image generator connection check failed: {e}",
        ) from e


@router.get("/types", response_model=list[str])
async def get_generator_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return ImageGeneratorRegistry.available_types()


@router.get("/types/meta", response_model=list[ImageGeneratorTypeMeta])
async def get_generator_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    response: list[ImageGeneratorTypeMeta] = []
    for generator_type in ImageGeneratorRegistry.available_types():
        runtime_cls = ImageGeneratorRegistry.get(generator_type)
        supported_types = [t.lower() for t in runtime_cls.supported_connector_types()]
        response.append(
            ImageGeneratorTypeMeta(
                type=generator_type,
                supported_connector_types=supported_types,
                requires_connector=len(supported_types) > 0,
            )
        )
    return response


@router.get("/types/{generator_type}/settings-schema", response_model=dict[str, Any])
async def get_generator_settings_schema(
    generator_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_runtime_cls(generator_type, status_code=status.HTTP_404_NOT_FOUND)
    return runtime_cls.settings_schema().model_json_schema()


@router.post("", response_model=ImageGeneratorResponse, status_code=status.HTTP_201_CREATED)
async def create_image_generator(
    data: ImageGeneratorCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    if data.permissions is not None:
        require_superuser(current_user)

    runtime_cls = _resolve_runtime_cls(data.type, status_code=status.HTTP_400_BAD_REQUEST)
    validated_settings = await _validate_settings(data.type, data.settings)
    validated_connector_id = await _validate_connector_link(
        user_id=current_user.id,
        connector_id=data.connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
        require_owner=True,
    )
    if data.check_connection:
        await _check_connection_or_http_error(
            runtime_cls=runtime_cls,
            settings=validated_settings,
            connector_id=validated_connector_id,
            connector_repo=connector_repo,
        )

    generator = await generator_repo.create(
        owner_id=current_user.id,
        generator_type=data.type,
        name=data.name,
        settings=validated_settings,
        connector_id=validated_connector_id,
        is_active=data.is_active,
    )
    if data.permissions is not None:
        await ResourcePermissionRepository(generator_repo.db).set_read_acl(
            resource_type="image_generator",
            resource_id=generator.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )
    return ImageGeneratorRepository.to_response(generator, can_edit=True)


@router.get("", response_model=list[ImageGeneratorResponse])
async def get_image_generators(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
    only_active: bool = Query(False, description="Only active image generators"),
):
    rows = await generator_repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        ImageGeneratorRepository.to_response(
            generator,
            can_edit=can_edit,
        )
        for generator, can_edit in rows
    ]


@router.get("/{generator_id}", response_model=ImageGeneratorResponse)
async def get_image_generator(
    generator_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    generator, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=generator_id,
        user_id=current_user.id,
        repository=generator_repo,
        not_found_detail="Image generator not found",
    )
    return ImageGeneratorRepository.to_response(generator, can_edit=can_edit)


@router.patch("/{generator_id}", response_model=ImageGeneratorResponse)
async def patch_image_generator(
    generator_id: uuid.UUID,
    data: ImageGeneratorPatchRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    generator = await _get_generator_with_write_check(
        generator_id=generator_id,
        user_id=current_user.id,
        generator_repo=generator_repo,
    )

    runtime_cls = _resolve_runtime_cls(generator.type, status_code=status.HTTP_400_BAD_REQUEST)
    update_data: dict[str, Any] = {}
    effective_settings = generator.settings or {}

    if "name" in data.model_fields_set:
        update_data["name"] = data.name

    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        effective_settings = await _validate_settings(generator.type, data.settings)
        update_data["settings"] = effective_settings

    effective_connector_id = (
        data.connector_id
        if "connector_id" in data.model_fields_set
        else generator.connector_id
    )
    validated_connector_id = await _validate_connector_link(
        user_id=current_user.id,
        connector_id=effective_connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
        connector_repo=connector_repo,
        require_owner=generator.owner_id == current_user.id,
    )
    if "connector_id" in data.model_fields_set:
        update_data["connector_id"] = validated_connector_id

    if data.check_connection:
        await _check_connection_or_http_error(
            runtime_cls=runtime_cls,
            settings=effective_settings,
            connector_id=validated_connector_id,
            connector_repo=connector_repo,
        )

    is_deactivating_current = False
    if "is_active" in data.model_fields_set:
        update_data["is_active"] = data.is_active
        is_deactivating_current = data.is_active is False

    if update_data:
        generator = await generator_repo.update(generator, **update_data)

    if is_deactivating_current:
        await clear_user_current_link_if_matches(
            db=db,
            owner_id=generator.owner_id,
            resource_id=generator.id,
            user_field_name="image_generator_id",
        )

    return ImageGeneratorRepository.to_response(generator, can_edit=True)


@router.delete("/{generator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image_generator(
    generator_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    generator = await _get_generator_with_write_check(
        generator_id=generator_id,
        user_id=current_user.id,
        generator_repo=generator_repo,
    )
    await generator_repo.delete(generator)
    await clear_user_current_link_if_matches(
        db=db,
        owner_id=generator.owner_id,
        resource_id=generator.id,
        user_field_name="image_generator_id",
    )
