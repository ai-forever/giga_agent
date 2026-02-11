import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr
from sqlalchemy import String, Boolean, DateTime, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT


# ============ SQLAlchemy Models ============


class User(Base):
    __tablename__ = "core_users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )
    settings: Mapped[dict | None] = mapped_column(
        JSON_VARIANT(), nullable=True, default=None
    )


# ============ Pydantic Schemas ============


class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: uuid.UUID
    settings: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserShort(BaseModel):
    """Короткая версия пользователя без дат"""

    id: uuid.UUID
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False
    settings: Optional[dict] = None

    class Config:
        from_attributes = True


class UserSettingsUpdate(BaseModel):
    """Схема для обновления настроек пользователя"""

    settings: dict


# ============ Repository ============


class UserRepository:
    """
    Repository для работы с пользователями в БД.
    Все методы работы с БД сосредоточены здесь.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        """Получить пользователя по email"""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Получить пользователя по UUID"""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        email: str,
        hashed_password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_active: bool = True,
        is_superuser: bool = False,
    ) -> User:
        """Создать нового пользователя"""
        user = User(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
            is_superuser=is_superuser,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update(
        self,
        user: User,
        **kwargs,
    ) -> User:
        """Обновить данные пользователя"""
        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_settings(
        self,
        user: User,
        settings: dict,
    ) -> User:
        """Обновить настройки пользователя (merge с существующими)"""
        current = dict(user.settings or {})
        current.update(settings)
        user.settings = current
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        """Удалить пользователя"""
        await self.db.delete(user)
        await self.db.commit()

    async def exists_by_email(self, email: str) -> bool:
        """Проверить существует ли пользователь с таким email"""
        user = await self.get_by_email(email)
        return user is not None

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        only_active: bool = False,
    ) -> list[User]:
        """Получить список пользователей"""
        query = select(User)
        if only_active:
            query = query.where(User.is_active == True)
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ============ Методы возвращающие Pydantic схемы ============

    async def get_by_email_response(self, email: str) -> UserResponse | None:
        """Получить пользователя по email (Pydantic response)"""
        user = await self.get_by_email(email)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def get_by_id_response(self, user_id: uuid.UUID) -> UserResponse | None:
        """Получить пользователя по UUID (Pydantic response)"""
        user = await self.get_by_id(user_id)
        if user:
            return UserResponse.model_validate(user)
        return None

    @staticmethod
    def to_response(user: User) -> UserResponse:
        """Преобразовать модель в Pydantic response"""
        return UserResponse.model_validate(user)

    @staticmethod
    def to_short(user: User) -> UserShort:
        """Преобразовать модель в короткий Pydantic response"""
        return UserShort.model_validate(user)
