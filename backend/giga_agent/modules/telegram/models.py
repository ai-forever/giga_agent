import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, Boolean, DateTime, Uuid, ForeignKey, BigInteger, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from giga_agent.core.db import Base


class TelegramBot(Base):
    __tablename__ = "telegram_bots"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    bot_token: Mapped[str] = mapped_column(String, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_username: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=datetime.utcnow, server_default=text("(CURRENT_TIMESTAMP)")
    )


class TelegramThread(Base):
    __tablename__ = "telegram_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("telegram_bots.id", ondelete="CASCADE"),
        index=True,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    langgraph_thread_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"), onupdate=datetime.utcnow
    )


class TelegramContact(Base):
    __tablename__ = "telegram_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("telegram_bots.id", ondelete="CASCADE"),
        index=True,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("(CURRENT_TIMESTAMP)"), onupdate=datetime.utcnow
    )


class TelegramBotCreate(BaseModel):
    bot_token: str
    is_enabled: bool = True


class TelegramBotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_token: str | None = None
    is_enabled: bool | None = None


class TelegramBotResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    is_enabled: bool
    bot_username: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TelegramContactResponse(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    telegram_chat_id: int
    telegram_username: str | None = None
    telegram_first_name: str | None = None
    telegram_last_name: str | None = None
    is_approved: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TelegramBotRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user(self, user_id: uuid.UUID) -> TelegramBot | None:
        result = await self.db.execute(
            select(TelegramBot).where(TelegramBot.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, bot_id: uuid.UUID) -> TelegramBot | None:
        result = await self.db.execute(
            select(TelegramBot).where(TelegramBot.id == bot_id)
        )
        return result.scalar_one_or_none()

    async def get_all_enabled(self) -> list[TelegramBot]:
        result = await self.db.execute(
            select(TelegramBot).where(TelegramBot.is_enabled.is_(True))
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: uuid.UUID,
        bot_token: str,
        is_enabled: bool = True,
        bot_username: str | None = None,
    ) -> TelegramBot:
        bot = TelegramBot(
            user_id=user_id,
            bot_token=bot_token,
            is_enabled=is_enabled,
            bot_username=bot_username,
        )
        self.db.add(bot)
        await self.db.commit()
        await self.db.refresh(bot)
        return bot

    async def update(self, bot: TelegramBot, **kwargs) -> TelegramBot:
        for key, value in kwargs.items():
            if hasattr(bot, key):
                setattr(bot, key, value)
        await self.db.commit()
        await self.db.refresh(bot)
        return bot

    async def delete(self, bot: TelegramBot) -> None:
        await self.db.delete(bot)
        await self.db.commit()

    async def get_thread(
        self, bot_id: uuid.UUID, telegram_chat_id: int
    ) -> TelegramThread | None:
        result = await self.db.execute(
            select(TelegramThread).where(
                TelegramThread.bot_id == bot_id,
                TelegramThread.telegram_chat_id == telegram_chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_thread(self, thread: TelegramThread) -> None:
        await self.db.delete(thread)
        await self.db.commit()

    async def touch_thread(self, thread: TelegramThread) -> None:
        thread.updated_at = datetime.utcnow()
        await self.db.commit()

    async def delete_expired_threads(
        self, bot_id: uuid.UUID, max_age_seconds: int
    ) -> int:
        from sqlalchemy import delete as sa_delete
        cutoff = datetime.utcnow() - __import__("datetime").timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            sa_delete(TelegramThread).where(
                TelegramThread.bot_id == bot_id,
                TelegramThread.updated_at < cutoff,
            )
        )
        await self.db.commit()
        return result.rowcount or 0

    async def create_thread(
        self,
        bot_id: uuid.UUID,
        telegram_chat_id: int,
        langgraph_thread_id: str,
    ) -> TelegramThread:
        thread = TelegramThread(
            bot_id=bot_id,
            telegram_chat_id=telegram_chat_id,
            langgraph_thread_id=langgraph_thread_id,
        )
        self.db.add(thread)
        await self.db.commit()
        await self.db.refresh(thread)
        return thread

    # --- Contact approval ---

    async def get_contact(
        self, bot_id: uuid.UUID, telegram_chat_id: int
    ) -> TelegramContact | None:
        result = await self.db.execute(
            select(TelegramContact).where(
                TelegramContact.bot_id == bot_id,
                TelegramContact.telegram_chat_id == telegram_chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_contact_by_id(self, contact_id: uuid.UUID) -> TelegramContact | None:
        result = await self.db.execute(
            select(TelegramContact).where(TelegramContact.id == contact_id)
        )
        return result.scalar_one_or_none()

    async def get_contacts_for_bot(self, bot_id: uuid.UUID) -> list[TelegramContact]:
        result = await self.db.execute(
            select(TelegramContact)
            .where(TelegramContact.bot_id == bot_id)
            .order_by(TelegramContact.created_at.desc())
        )
        return list(result.scalars().all())

    async def upsert_contact(
        self,
        bot_id: uuid.UUID,
        telegram_chat_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> TelegramContact:
        existing = await self.get_contact(bot_id, telegram_chat_id)
        if existing is not None:
            existing.telegram_username = username
            existing.telegram_first_name = first_name
            existing.telegram_last_name = last_name
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        contact = TelegramContact(
            bot_id=bot_id,
            telegram_chat_id=telegram_chat_id,
            telegram_username=username,
            telegram_first_name=first_name,
            telegram_last_name=last_name,
            is_approved=False,
        )
        self.db.add(contact)
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def set_contact_approved(
        self, contact_id: uuid.UUID, approved: bool
    ) -> TelegramContact | None:
        contact = await self.get_contact_by_id(contact_id)
        if contact is None:
            return None
        contact.is_approved = approved
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def delete_contact(self, contact: TelegramContact) -> None:
        await self.db.delete(contact)
        await self.db.commit()
