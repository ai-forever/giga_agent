"""API routes for Telegram bot management."""

from __future__ import annotations

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.models.users import UserShort
from pydantic import BaseModel

from giga_agent.modules.telegram.models import (
    TelegramBotCreate,
    TelegramBotUpdate,
    TelegramBotResponse,
    TelegramBotRepository,
    TelegramContactResponse,
)
from giga_agent.modules.telegram.bot import get_bot_manager

logger = get_logger(__name__)
router = APIRouter(tags=["telegram"])


async def _validate_token(token: str) -> str | None:
    try:
        bot = Bot(token=token)
        info = await bot.get_me()
        await bot.session.close()
        return info.username
    except Exception:
        return None


@router.get("/bot", response_model=TelegramBotResponse | None)
async def get_bot(
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        return None
    return TelegramBotResponse.model_validate(bot)


@router.post("/bot", response_model=TelegramBotResponse, status_code=201)
async def create_bot(
    body: TelegramBotCreate,
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    existing = await repo.get_by_user(current_user.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Telegram bot already configured")

    username = await _validate_token(body.bot_token)
    if username is None:
        raise HTTPException(status_code=400, detail="Invalid Telegram bot token")

    bot = await repo.create(
        user_id=current_user.id,
        bot_token=body.bot_token,
        is_enabled=body.is_enabled,
        bot_username=username,
    )

    if bot.is_enabled:
        manager = get_bot_manager()
        await manager.start_bot(bot.id)

    return TelegramBotResponse.model_validate(bot)


@router.patch("/bot", response_model=TelegramBotResponse)
async def update_bot(
    body: TelegramBotUpdate,
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Telegram bot not configured")

    updates: dict = {}
    if body.bot_token is not None:
        username = await _validate_token(body.bot_token)
        if username is None:
            raise HTTPException(status_code=400, detail="Invalid Telegram bot token")
        updates["bot_token"] = body.bot_token
        updates["bot_username"] = username

    if body.is_enabled is not None:
        updates["is_enabled"] = body.is_enabled

    if updates:
        bot = await repo.update(bot, **updates)

    manager = get_bot_manager()
    if bot.is_enabled:
        await manager.restart_bot(bot.id)
    else:
        await manager.stop_bot(bot.id)

    return TelegramBotResponse.model_validate(bot)


@router.delete("/bot", status_code=204)
async def delete_bot(
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Telegram bot not configured")

    manager = get_bot_manager()
    await manager.stop_bot(bot.id)
    await repo.delete(bot)


@router.get("/bot/status")
async def bot_status(
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        return {"configured": False, "running": False}

    manager = get_bot_manager()
    return {
        "configured": True,
        "running": manager.is_running(bot.id),
        "bot_username": bot.bot_username,
        "is_enabled": bot.is_enabled,
    }


# --- Contact approval endpoints ---


class ContactApprovalUpdate(BaseModel):
    is_approved: bool


@router.get("/contacts", response_model=list[TelegramContactResponse])
async def list_contacts(
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        return []
    contacts = await repo.get_contacts_for_bot(bot.id)
    return [TelegramContactResponse.model_validate(c) for c in contacts]


@router.patch("/contacts/{contact_id}", response_model=TelegramContactResponse)
async def update_contact(
    contact_id: str,
    body: ContactApprovalUpdate,
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    import uuid as _uuid

    try:
        cid = _uuid.UUID(contact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid contact id")

    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not configured")

    contact = await repo.get_contact_by_id(cid)
    if contact is None or contact.bot_id != bot.id:
        raise HTTPException(status_code=404, detail="Contact not found")

    updated = await repo.set_contact_approved(cid, body.is_approved)
    return TelegramContactResponse.model_validate(updated)


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: str,
    current_user: UserShort = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session),
):
    import uuid as _uuid

    try:
        cid = _uuid.UUID(contact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid contact id")

    repo = TelegramBotRepository(db)
    bot = await repo.get_by_user(current_user.id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not configured")

    contact = await repo.get_contact_by_id(cid)
    if contact is None or contact.bot_id != bot.id:
        raise HTTPException(status_code=404, detail="Contact not found")

    await repo.delete_contact(contact)
