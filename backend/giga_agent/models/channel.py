import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT


class ChannelBot(Base):
    """Generic messenger channel instance owned by a user."""

    __tablename__ = "core_channel_bots"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_channel_bots_user_id"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ChannelThread(Base):
    """Agent thread mapping for an external messenger chat/user pair."""

    __tablename__ = "core_channel_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_channel_bots.id", name="fk_core_channel_threads_bot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    external_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    langgraph_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ChannelContact(Base):
    """Generic messenger contact or participant metadata."""

    __tablename__ = "core_channel_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_channel_bots.id", name="fk_core_channel_contacts_bot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    external_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    chat_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ChannelBotBase(BaseModel):
    channel_type: str
    is_enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ChannelBotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_type: str
    is_enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ChannelBotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool | None = None
    settings: dict[str, Any] | None = None


class ChannelBotResponse(ChannelBotBase):
    id: uuid.UUID
    user_id: uuid.UUID
    bot_username: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelTypeMeta(BaseModel):
    type: str


class ChannelContactApprovalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_approved: bool


class ChannelThreadResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    external_chat_id: str
    external_user_id: str | None = None
    langgraph_thread_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelContactResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    external_chat_id: str
    external_user_id: str | None = None
    chat_type: str | None = None
    chat_title: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_approved: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelBotRepository:
    """Repository for generic channel instances, contacts, and threads."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _external_user_clause(column: Any, external_user_id: str | None) -> Any:
        if external_user_id is None:
            return column.is_(None)
        return column == external_user_id

    async def get_by_id(self, bot_id: uuid.UUID) -> ChannelBot | None:
        result = await self.db.execute(select(ChannelBot).where(ChannelBot.id == bot_id))
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        channel_type: str | None = None,
    ) -> list[ChannelBot]:
        query = select(ChannelBot).where(ChannelBot.user_id == user_id)
        if channel_type is not None:
            query = query.where(ChannelBot.channel_type == channel_type)
        query = query.order_by(ChannelBot.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_enabled(
        self,
        *,
        channel_type: str | None = None,
    ) -> list[ChannelBot]:
        query = select(ChannelBot).where(ChannelBot.is_enabled.is_(True))
        if channel_type is not None:
            query = query.where(ChannelBot.channel_type == channel_type)
        query = query.order_by(ChannelBot.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        channel_type: str,
        settings: dict[str, Any] | None = None,
        is_enabled: bool = True,
        bot_username: str | None = None,
    ) -> ChannelBot:
        bot = ChannelBot(
            user_id=user_id,
            channel_type=channel_type,
            settings=settings or {},
            is_enabled=is_enabled,
            bot_username=bot_username,
        )
        self.db.add(bot)
        await self.db.commit()
        await self.db.refresh(bot)
        return bot

    async def update(self, bot: ChannelBot, **kwargs: Any) -> ChannelBot:
        for key, value in kwargs.items():
            if hasattr(bot, key):
                setattr(bot, key, value)
        await self.db.commit()
        await self.db.refresh(bot)
        return bot

    async def delete(self, bot: ChannelBot) -> None:
        await self.db.delete(bot)
        await self.db.commit()

    async def get_thread(
        self,
        bot_id: uuid.UUID,
        external_chat_id: str,
        external_user_id: str | None = None,
    ) -> ChannelThread | None:
        result = await self.db.execute(
            select(ChannelThread).where(
                ChannelThread.bot_id == bot_id,
                ChannelThread.external_chat_id == external_chat_id,
                self._external_user_clause(
                    ChannelThread.external_user_id, external_user_id
                ),
            )
        )
        return result.scalar_one_or_none()

    async def create_thread(
        self,
        *,
        bot_id: uuid.UUID,
        external_chat_id: str,
        langgraph_thread_id: str,
        external_user_id: str | None = None,
    ) -> ChannelThread:
        thread = ChannelThread(
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            external_user_id=external_user_id,
            langgraph_thread_id=langgraph_thread_id,
        )
        self.db.add(thread)
        await self.db.commit()
        await self.db.refresh(thread)
        return thread

    async def touch_thread(self, thread: ChannelThread) -> None:
        thread.updated_at = datetime.utcnow()
        await self.db.commit()

    async def delete_thread(self, thread: ChannelThread) -> None:
        await self.db.delete(thread)
        await self.db.commit()

    async def delete_expired_threads(
        self,
        *,
        bot_id: uuid.UUID,
        max_age_seconds: int,
    ) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            delete(ChannelThread).where(
                ChannelThread.bot_id == bot_id,
                ChannelThread.updated_at < cutoff,
            )
        )
        await self.db.commit()
        return result.rowcount or 0

    async def get_contact(
        self,
        bot_id: uuid.UUID,
        external_chat_id: str,
        external_user_id: str | None = None,
    ) -> ChannelContact | None:
        result = await self.db.execute(
            select(ChannelContact).where(
                ChannelContact.bot_id == bot_id,
                ChannelContact.external_chat_id == external_chat_id,
                self._external_user_clause(
                    ChannelContact.external_user_id, external_user_id
                ),
            )
        )
        return result.scalar_one_or_none()

    async def get_contact_by_id(self, contact_id: uuid.UUID) -> ChannelContact | None:
        result = await self.db.execute(
            select(ChannelContact).where(ChannelContact.id == contact_id)
        )
        return result.scalar_one_or_none()

    async def get_contacts_for_bot(self, bot_id: uuid.UUID) -> list[ChannelContact]:
        result = await self.db.execute(
            select(ChannelContact)
            .where(ChannelContact.bot_id == bot_id)
            .order_by(ChannelContact.created_at.desc())
        )
        return list(result.scalars().all())

    async def upsert_contact(
        self,
        *,
        bot_id: uuid.UUID,
        external_chat_id: str,
        external_user_id: str | None = None,
        chat_type: str | None = None,
        chat_title: str | None = None,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> ChannelContact:
        existing = await self.get_contact(
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            external_user_id=external_user_id,
        )
        if existing is not None:
            existing.chat_type = chat_type
            existing.chat_title = chat_title
            existing.username = username
            existing.first_name = first_name
            existing.last_name = last_name
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        contact = ChannelContact(
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            external_user_id=external_user_id,
            chat_type=chat_type,
            chat_title=chat_title,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_approved=False,
        )
        self.db.add(contact)
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def set_contact_approved(
        self,
        contact_id: uuid.UUID,
        approved: bool,
    ) -> ChannelContact | None:
        contact = await self.get_contact_by_id(contact_id)
        if contact is None:
            return None
        contact.is_approved = approved
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def set_contact_approved_by_external_id(
        self,
        *,
        bot_id: uuid.UUID,
        external_chat_id: str,
        approved: bool,
        external_user_id: str | None = None,
    ) -> ChannelContact | None:
        contact = await self.get_contact(
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            external_user_id=external_user_id,
        )
        if contact is None:
            return None
        contact.is_approved = approved
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def delete_contact(self, contact: ChannelContact) -> None:
        await self.db.delete(contact)
        await self.db.commit()
