"""Команда инстанса: системная группа «All Members».

Инстанс GigaAgent = одна команда. Системная группа объединяет всех
пользователей; членство автоматическое (создание юзера/вступление по
инвайту), выход и удаление группы запрещены. Ресурс, расшаренный на эту
группу (ResourcePermission read), становится «доступен команде».
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.events import event_bus
from giga_agent.core.logging import get_logger
from giga_agent.models.group import Group, GroupMember
from giga_agent.models.users import User

logger = get_logger(__name__)

# Маркер системной группы в Group.data.
SYSTEM_GROUP_ALL_MEMBERS = "all_members"
ALL_MEMBERS_NAME = "All Members"

_SUBSCRIBED = False
_LOCK = asyncio.Lock()


def is_system_group(group: Group) -> bool:
    data = group.data if isinstance(group.data, dict) else {}
    return data.get("system") == SYSTEM_GROUP_ALL_MEMBERS


async def find_all_members_group(session: AsyncSession) -> Group | None:
    result = await session.execute(select(Group))
    for group in result.scalars().all():
        if is_system_group(group):
            return group
    return None


async def _backfill_members(session: AsyncSession, group_id: uuid.UUID) -> int:
    """Добавляет в группу всех пользователей, которых там ещё нет."""
    existing = {
        row[0]
        for row in (
            await session.execute(
                select(GroupMember.user_id).where(GroupMember.group_id == group_id)
            )
        ).all()
    }
    all_ids = [row[0] for row in (await session.execute(select(User.id))).all()]
    missing = [uid for uid in all_ids if uid not in existing]
    for uid in missing:
        session.add(GroupMember(group_id=group_id, user_id=uid))
    return len(missing)


async def ensure_all_members_group(session: AsyncSession) -> Group:
    """Создаёт системную группу при первом старте и бэкфиллит членство.

    Идемпотентно: повторные вызовы ничего не ломают.
    """
    group = await find_all_members_group(session)
    if group is None:
        # Владелец группы — owner инстанса (или самый ранний пользователь).
        owner_row = await session.execute(
            select(User.id)
            .order_by((User.role != "owner").asc(), User.created_at.asc())
            .limit(1)
        )
        owner_id = owner_row.scalar_one_or_none()
        if owner_id is None:
            raise RuntimeError("Cannot create All Members group: no users exist")
        group = Group(
            owner_id=owner_id,
            name=ALL_MEMBERS_NAME,
            description="Все участники команды (системная группа)",
            data={"system": SYSTEM_GROUP_ALL_MEMBERS},
        )
        session.add(group)
        await session.flush()
        logger.info("Created system group 'All Members' (%s)", group.id)

    added = await _backfill_members(session, group.id)
    await session.commit()
    if added:
        logger.info("All Members: backfilled %d member(s)", added)
    return group


async def _handle_user_created(event) -> None:
    """Новый пользователь автоматически попадает в All Members."""
    from giga_agent.core.db import get_session_factory

    try:
        factory = await get_session_factory()
        async with factory() as session:
            group = await find_all_members_group(session)
            if group is None:
                group = await ensure_all_members_group(session)
                return  # ensure уже добавил всех, включая нового
            exists = await session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group.id,
                    GroupMember.user_id == event.user_id,
                )
            )
            if exists.scalar_one_or_none() is None:
                session.add(
                    GroupMember(group_id=group.id, user_id=event.user_id)
                )
                await session.commit()
    except Exception:
        logger.exception(
            "Failed to add user %s to All Members", getattr(event, "user_id", "?")
        )


async def ensure_subscribed() -> None:
    """Подписка на UserCreatedEvent (однократная)."""
    from giga_agent.modules.auth.events import UserCreatedEvent

    global _SUBSCRIBED
    async with _LOCK:
        if _SUBSCRIBED:
            return
        event_bus.subscribe(UserCreatedEvent, _handle_user_created)
        _SUBSCRIBED = True
