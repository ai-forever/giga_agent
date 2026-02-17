"""API router for image generators."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.image_generator import (
    ImageGenerator,
    ImageGeneratorCreate,
    ImageGeneratorRepository,
    ImageGeneratorResponse,
)
from giga_agent.models.users import User, UserRepository, UserShort
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(prefix="/image", tags=["generators"])


class ImageGeneratorPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    settings: dict[str, Any] | None = None
    connector_id: uuid.UUID | None = None
    is_active: bool | None = None


class CurrentImageGeneratorUpdate(BaseModel):
    image_generator_id: uuid.UUID | None = None


class CurrentImageGeneratorResponse(BaseModel):
    image_generator_id: uuid.UUID | None
    generator: ImageGeneratorResponse | None


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
                detail="This image generator type does not support connector_id.",
            )
        return None

    if connector_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "connector_id is required for this image generator type. "
                f"Supported connector types: {normalized_supported}"
            ),
        )

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
                f"image generator. Supported: {normalized_supported}"
            ),
        )

    return connector_id


async def _get_generator_with_owner_check(
    *,
    generator_id: uuid.UUID,
    owner_id: uuid.UUID,
    generator_repo: ImageGeneratorRepository,
) -> ImageGenerator:
    generator = await generator_repo.get_by_id(generator_id)
    if generator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image generator not found",
        )
    if generator.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return generator


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


async def _set_user_current_image_generator(
    *,
    db: AsyncSession,
    owner_id: uuid.UUID,
    image_generator_id: uuid.UUID | None,
) -> None:
    user = await _get_user_model(db=db, owner_id=owner_id)
    user.image_generator_id = image_generator_id
    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(owner_id)


async def _clear_current_if_matches(
    *,
    db: AsyncSession,
    owner_id: uuid.UUID,
    image_generator_id: uuid.UUID,
) -> bool:
    user = await _get_user_model(db=db, owner_id=owner_id)
    if user.image_generator_id != image_generator_id:
        return False

    user.image_generator_id = None
    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(owner_id)
    return True


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
    runtime_cls = _resolve_runtime_cls(data.type, status_code=status.HTTP_400_BAD_REQUEST)
    validated_settings = await _validate_settings(data.type, data.settings)
    validated_connector_id = await _validate_connector_link(
        owner_id=current_user.id,
        connector_id=data.connector_id,
        supported_connector_types=runtime_cls.supported_connector_types(),
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
    return ImageGeneratorRepository.to_response(generator)


@router.get("", response_model=list[ImageGeneratorResponse])
async def get_image_generators(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
    only_active: bool = Query(False, description="Only active image generators"),
):
    generators = await generator_repo.get_by_owner(current_user.id, only_active=only_active)
    return [ImageGeneratorRepository.to_response(g) for g in generators]


@router.get("/current", response_model=CurrentImageGeneratorResponse)
async def get_current_image_generator(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    user = await _get_user_model(db=db, owner_id=current_user.id)
    if user.image_generator_id is None:
        return CurrentImageGeneratorResponse(image_generator_id=None, generator=None)

    generator = await generator_repo.get_by_id(user.image_generator_id)
    if generator is None or generator.owner_id != current_user.id or not generator.is_active:
        await _set_user_current_image_generator(
            db=db,
            owner_id=current_user.id,
            image_generator_id=None,
        )
        return CurrentImageGeneratorResponse(image_generator_id=None, generator=None)

    return CurrentImageGeneratorResponse(
        image_generator_id=generator.id,
        generator=ImageGeneratorRepository.to_response(generator),
    )


@router.patch("/current", response_model=CurrentImageGeneratorResponse)
async def patch_current_image_generator(
    data: CurrentImageGeneratorUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    if data.image_generator_id is None:
        await _set_user_current_image_generator(
            db=db,
            owner_id=current_user.id,
            image_generator_id=None,
        )
        return CurrentImageGeneratorResponse(image_generator_id=None, generator=None)

    generator = await _get_generator_with_owner_check(
        generator_id=data.image_generator_id,
        owner_id=current_user.id,
        generator_repo=generator_repo,
    )
    if not generator.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image generator must be active",
        )

    await _set_user_current_image_generator(
        db=db,
        owner_id=current_user.id,
        image_generator_id=generator.id,
    )
    return CurrentImageGeneratorResponse(
        image_generator_id=generator.id,
        generator=ImageGeneratorRepository.to_response(generator),
    )


@router.get("/{generator_id}", response_model=ImageGeneratorResponse)
async def get_image_generator(
    generator_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    generator = await _get_generator_with_owner_check(
        generator_id=generator_id,
        owner_id=current_user.id,
        generator_repo=generator_repo,
    )
    return ImageGeneratorRepository.to_response(generator)


@router.patch("/{generator_id}", response_model=ImageGeneratorResponse)
async def patch_image_generator(
    generator_id: uuid.UUID,
    data: ImageGeneratorPatchRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
    connector_repo: Annotated[ConnectorRepository, Depends(get_connector_repository)],
):
    generator = await _get_generator_with_owner_check(
        generator_id=generator_id,
        owner_id=current_user.id,
        generator_repo=generator_repo,
    )

    runtime_cls = _resolve_runtime_cls(generator.type, status_code=status.HTTP_400_BAD_REQUEST)
    update_data: dict[str, Any] = {}

    if "name" in data.model_fields_set:
        update_data["name"] = data.name

    if "settings" in data.model_fields_set:
        if data.settings is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="settings must be an object when provided",
            )
        update_data["settings"] = await _validate_settings(generator.type, data.settings)

    effective_connector_id = (
        data.connector_id
        if "connector_id" in data.model_fields_set
        else generator.connector_id
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
        generator = await generator_repo.update(generator, **update_data)

    if is_deactivating_current:
        await _clear_current_if_matches(
            db=db,
            owner_id=current_user.id,
            image_generator_id=generator.id,
        )

    return ImageGeneratorRepository.to_response(generator)


@router.delete("/{generator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image_generator(
    generator_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    generator_repo: Annotated[ImageGeneratorRepository, Depends(get_image_generator_repository)],
):
    generator = await _get_generator_with_owner_check(
        generator_id=generator_id,
        owner_id=current_user.id,
        generator_repo=generator_repo,
    )
    await generator_repo.delete(generator)
    await _clear_current_if_matches(
        db=db,
        owner_id=current_user.id,
        image_generator_id=generator.id,
    )
