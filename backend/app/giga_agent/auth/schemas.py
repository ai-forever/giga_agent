# Re-export for backward compatibility
# Схемы перенесены в giga_agent.models.users
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from giga_agent.models.users import (
    UserBase,
    UserCreate,
    UserResponse,
    UserShort,
    UserSettingsUpdate,
)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[UUID] = None


__all__ = [
    "Token",
    "TokenData",
    "UserBase",
    "UserCreate",
    "UserResponse",
    "UserSettingsUpdate",
    "UserShort",
]
