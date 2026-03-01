from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models.users import User, UserRepository


async def get_user_model(
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


async def clear_user_current_link_if_matches(
    *,
    db: AsyncSession,
    owner_id: uuid.UUID,
    resource_id: uuid.UUID,
    user_field_name: str,
) -> bool:
    user = await get_user_model(db=db, owner_id=owner_id)
    if getattr(user, user_field_name) != resource_id:
        return False

    setattr(user, user_field_name, None)
    await db.commit()
    await db.refresh(user)
    await UserRepository.invalidate_cache(owner_id)
    return True
