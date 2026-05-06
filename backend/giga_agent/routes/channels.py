"""Core API router for channel instances and contacts."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import giga_agent.channels  # noqa: F401
from giga_agent.channels.manager import get_channel_manager
from giga_agent.channels.registry import ChannelRegistry
from giga_agent.core.db import get_session
from giga_agent.models.channel import (
    ChannelBot,
    ChannelBotCreate,
    ChannelBotRepository,
    ChannelBotResponse,
    ChannelBotUpdate,
    ChannelContact,
    ChannelContactApprovalUpdate,
    ChannelContactResponse,
    ChannelTypeMeta,
)
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes._shared.schema import build_settings_schema_with_computed_defaults

router = APIRouter(prefix="/channels", tags=["channels"])


def _get_channel_manager():
    return get_channel_manager()


async def get_channel_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ChannelBotRepository:
    return ChannelBotRepository(db)


def _resolve_channel_runtime_cls(channel_type: str, *, status_code: int) -> type:
    if not ChannelRegistry.is_registered(channel_type):
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Unknown channel type: '{channel_type}'. "
                f"Available: {ChannelRegistry.available_types()}"
            ),
        )
    return ChannelRegistry.get(channel_type)


async def _validate_settings(
    channel_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await ChannelRegistry.validate_settings(channel_type, settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


async def _resolve_instance_metadata_or_422(
    *,
    channel_type: str,
    settings: dict[str, Any],
):
    try:
        return await ChannelRegistry.resolve_instance_metadata(channel_type, settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Channel metadata resolution failed: {e}",
        ) from e


async def _get_owned_bot(
    *,
    bot_id: uuid.UUID,
    user_id: uuid.UUID,
    channel_repo: ChannelBotRepository,
) -> ChannelBot:
    bot = await channel_repo.get_by_id(bot_id)
    if bot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel bot not found",
        )
    if bot.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return bot


async def _get_owned_contact(
    *,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    user_id: uuid.UUID,
    channel_repo: ChannelBotRepository,
) -> tuple[ChannelBot, ChannelContact]:
    bot = await _get_owned_bot(bot_id=bot_id, user_id=user_id, channel_repo=channel_repo)
    contact = await channel_repo.get_contact_by_id(contact_id)
    if contact is None or contact.bot_id != bot.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )
    return bot, contact


@router.get("/types", response_model=list[str])
async def get_channel_types(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return ChannelRegistry.available_types()


@router.get("/types/meta", response_model=list[ChannelTypeMeta])
async def get_channel_types_meta(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    return [ChannelTypeMeta(type=item) for item in ChannelRegistry.available_types()]


@router.get("/types/{channel_type}/settings-schema", response_model=dict[str, Any])
async def get_channel_settings_schema(
    channel_type: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    runtime_cls = _resolve_channel_runtime_cls(
        channel_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return build_settings_schema_with_computed_defaults(runtime_cls.settings_schema())


@router.get("", response_model=list[ChannelBotResponse])
async def list_channel_bots(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
    channel_type: str | None = Query(default=None),
):
    if channel_type is not None:
        _resolve_channel_runtime_cls(
            channel_type,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    bots = await channel_repo.list_by_user(current_user.id, channel_type=channel_type)
    return [ChannelBotResponse.model_validate(bot) for bot in bots]


@router.get("/{bot_id}", response_model=ChannelBotResponse)
async def get_channel_bot(
    bot_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    bot = await _get_owned_bot(
        bot_id=bot_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )
    return ChannelBotResponse.model_validate(bot)


@router.post("", response_model=ChannelBotResponse, status_code=status.HTTP_201_CREATED)
async def create_channel_bot(
    data: ChannelBotCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    _resolve_channel_runtime_cls(
        data.channel_type,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    validated_settings = await _validate_settings(data.channel_type, data.settings)
    metadata = await _resolve_instance_metadata_or_422(
        channel_type=data.channel_type,
        settings=validated_settings,
    )

    bot = await channel_repo.create(
        user_id=current_user.id,
        channel_type=data.channel_type,
        settings=validated_settings,
        is_enabled=data.is_enabled,
        bot_username=metadata.bot_username,
    )
    if bot.is_enabled:
        await _get_channel_manager().start_bot(bot.id)
    return ChannelBotResponse.model_validate(bot)


@router.patch("/{bot_id}", response_model=ChannelBotResponse)
async def update_channel_bot(
    bot_id: uuid.UUID,
    data: ChannelBotUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    bot = await _get_owned_bot(
        bot_id=bot_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )

    updates: dict[str, Any] = {}
    if data.settings is not None:
        validated_settings = await _validate_settings(bot.channel_type, data.settings)
        metadata = await _resolve_instance_metadata_or_422(
            channel_type=bot.channel_type,
            settings=validated_settings,
        )
        updates["settings"] = validated_settings
        updates["bot_username"] = metadata.bot_username

    if data.is_enabled is not None:
        updates["is_enabled"] = data.is_enabled

    manager = _get_channel_manager()
    should_restart = False
    previous_enabled = bot.is_enabled
    if updates:
        bot = await channel_repo.update(bot, **updates)
        should_restart = data.settings is not None and bot.is_enabled

    if data.is_enabled is not None:
        if bot.is_enabled and not previous_enabled:
            await manager.start_bot(bot.id)
        elif not bot.is_enabled and previous_enabled:
            await manager.stop_bot(bot.id)
    elif should_restart:
        await manager.restart_bot(bot.id)

    return ChannelBotResponse.model_validate(bot)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel_bot(
    bot_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    bot = await _get_owned_bot(
        bot_id=bot_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )
    await _get_channel_manager().stop_bot(bot.id)
    await channel_repo.delete(bot)


@router.get("/{bot_id}/contacts", response_model=list[ChannelContactResponse])
async def list_channel_contacts(
    bot_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    bot = await _get_owned_bot(
        bot_id=bot_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )
    contacts = await channel_repo.get_contacts_for_bot(bot.id)
    return [ChannelContactResponse.model_validate(contact) for contact in contacts]


@router.patch(
    "/{bot_id}/contacts/by-chat/{external_chat_id}",
    response_model=ChannelContactResponse,
)
async def update_channel_contact_by_chat_id(
    bot_id: uuid.UUID,
    external_chat_id: str,
    data: ChannelContactApprovalUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
    external_user_id: str | None = Query(default=None),
):
    bot = await _get_owned_bot(
        bot_id=bot_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )
    updated = await channel_repo.set_contact_approved_by_external_id(
        bot_id=bot.id,
        external_chat_id=external_chat_id,
        external_user_id=external_user_id,
        approved=data.is_approved,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )
    return ChannelContactResponse.model_validate(updated)


@router.delete("/{bot_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel_contact(
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    channel_repo: Annotated[ChannelBotRepository, Depends(get_channel_repository)],
):
    _, contact = await _get_owned_contact(
        bot_id=bot_id,
        contact_id=contact_id,
        user_id=current_user.id,
        channel_repo=channel_repo,
    )
    await channel_repo.delete_contact(contact)
