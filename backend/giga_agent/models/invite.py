"""Приглашения в команду (инстанс = одна команда).

Флоу: админ создаёт инвайт → получает ссылку /join/<token> (токен показывается
один раз, в БД хранится только SHA-256 хэш) → приглашённый открывает ссылку,
задаёт email/пароль и попадает в команду с ролью и группами из инвайта.
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import JSON_VARIANT, Base
from giga_agent.core.time import default_tz

DEFAULT_INVITE_TTL_DAYS = 7


def generate_invite_token() -> str:
    """URL-safe токен приглашения (возвращается пользователю один раз)."""
    return _secrets.token_urlsafe(32)


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Invite(Base):
    __tablename__ = "core_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # Если задан — принять приглашение можно только с этой почтой.
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default="member"
    )
    group_ids: Mapped[list | None] = mapped_column(
        JSON_VARIANT(), nullable=True, default=None
    )
    # Онбординг «вошёл и работает»: скопировать runtime-ссылки (llm_id и пр.)
    # создателя инвайта + выдать read-права на них (как в админ-создании юзера).
    copy_runtime_ids: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    copy_module_secrets: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    max_uses: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    used_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_invites_created_by"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    def is_usable(self, now: datetime | None = None) -> tuple[bool, str]:
        """(usable, причина-код). Причина не раскрывается публично."""
        now = now or datetime.now(default_tz())
        if self.revoked_at is not None:
            return False, "revoked"
        if self.expires_at is not None:
            # SQLite возвращает DateTime(timezone=True) без tzinfo; значение
            # пишется в UTC (см. create), поэтому доводим до aware именно в UTC
            # перед сравнением (на Postgres no-op). Сравнение aware-дат идёт по
            # абсолютному моменту, tz у now роли не играет.
            expires_at = self.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                return False, "expired"
        if self.used_count >= self.max_uses:
            return False, "exhausted"
        return True, "ok"


# ============ Pydantic Schemas ============


class InviteCreate(BaseModel):
    email: Optional[EmailStr] = None
    role: Literal["member", "admin"] = "member"
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    copy_runtime_ids: bool = True
    copy_module_secrets: bool = False
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int = Field(default=DEFAULT_INVITE_TTL_DAYS, ge=1, le=365 * 2)


class InviteResponse(BaseModel):
    id: uuid.UUID
    email: Optional[str] = None
    role: str
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    copy_runtime_ids: bool
    copy_module_secrets: bool
    max_uses: int
    used_count: int
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    created_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True


class InviteCreatedResponse(InviteResponse):
    """Ответ на создание: содержит токен — показывается ровно один раз."""

    token: str
    join_path: str


class JoinInfo(BaseModel):
    """Публичная информация о приглашении для страницы /join/<token>."""

    valid: bool
    email: Optional[str] = None  # если задан — поле почты фиксировано
    role: Optional[str] = None


class JoinRequest(BaseModel):
    token: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# ============ Repository ============


class InviteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        data: InviteCreate,
        created_by: uuid.UUID,
        commit: bool = True,
    ) -> tuple[Invite, str]:
        token = generate_invite_token()
        invite = Invite(
            token_hash=hash_invite_token(token),
            email=str(data.email) if data.email else None,
            role=data.role,
            group_ids=[str(gid) for gid in data.group_ids],
            copy_runtime_ids=data.copy_runtime_ids,
            copy_module_secrets=data.copy_module_secrets,
            max_uses=data.max_uses,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=data.expires_in_days),
            created_by=created_by,
        )
        self.db.add(invite)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(invite)
        return invite, token

    async def get_all(self) -> list[Invite]:
        result = await self.db.execute(
            select(Invite).order_by(Invite.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, invite_id: uuid.UUID) -> Invite | None:
        result = await self.db.execute(select(Invite).where(Invite.id == invite_id))
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> Invite | None:
        result = await self.db.execute(
            select(Invite).where(Invite.token_hash == hash_invite_token(token))
        )
        return result.scalar_one_or_none()

    async def get_by_token_for_update(self, token: str) -> Invite | None:
        """Строчная блокировка на время принятия инвайта (гонка used_count)."""
        result = await self.db.execute(
            select(Invite)
            .where(Invite.token_hash == hash_invite_token(token))
            .with_for_update()
        )
        return result.scalar_one_or_none()


def invite_to_response(invite: Invite) -> InviteResponse:
    return InviteResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        group_ids=[uuid.UUID(g) for g in (invite.group_ids or [])],
        copy_runtime_ids=invite.copy_runtime_ids,
        copy_module_secrets=invite.copy_module_secrets,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        expires_at=invite.expires_at,
        revoked_at=invite.revoked_at,
        created_by=invite.created_by,
        created_at=invite.created_at,
    )
