import uuid
from datetime import datetime
from typing import Literal, Optional

from cashews import cache
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import String, Boolean, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT

# Ensure referenced core tables are registered in metadata alongside User.
import giga_agent.models.connector  # noqa: F401
import giga_agent.models.embedding  # noqa: F401
import giga_agent.models.image_generator  # noqa: F401
import giga_agent.models.llm  # noqa: F401
import giga_agent.models.sandbox  # noqa: F401
import giga_agent.models.search_engine  # noqa: F401


# ============ Roles ============

# Роли команды (инстанс = одна команда):
#   owner  — первый пользователь; всё + управление админами; не деактивируется
#   admin  — коннекторы/LLM/секреты, приглашения, группы, управление member'ами
#   member — пользуется расшаренными ресурсами; свои данные приватны
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER)

# Иерархия для проверок вида "минимум admin".
_ROLE_RANK = {ROLE_MEMBER: 0, ROLE_ADMIN: 1, ROLE_OWNER: 2}


def role_at_least(role: str | None, minimum: str) -> bool:
    return _ROLE_RANK.get(role or ROLE_MEMBER, 0) >= _ROLE_RANK[minimum]


def role_implies_superuser(role: str | None) -> bool:
    """is_superuser поддерживается синхронно с role для обратной совместимости."""
    return role in (ROLE_OWNER, ROLE_ADMIN)


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
    # Источник правды по роли в команде; is_superuser держится синхронным
    # (role in {owner, admin} => is_superuser=True) для старых проверок.
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ROLE_MEMBER, server_default=ROLE_MEMBER
    )
    experimental_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )
    settings: Mapped[dict | None] = mapped_column(
        JSON_VARIANT(), nullable=True, default=None
    )
    secrets: Mapped[dict | None] = mapped_column(
        JSON_VARIANT(), nullable=True, default=None
    )
    image_generator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_image_generators.id",
            name="fk_core_users_image_generator_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )
    search_engine_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_search_engines.id",
            name="fk_core_users_search_engine_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )
    embedding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_embeddings.id",
            name="fk_core_users_embedding_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )
    llm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_llms.id",
            name="fk_core_users_llm_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )
    fast_llm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_llms.id",
            name="fk_core_users_fast_llm_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )
    sandbox_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_sandbox_providers.id",
            name="fk_core_users_sandbox_provider_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
        default=None,
    )


# ============ Pydantic Schemas ============


class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False
    experimental_mode: bool = True
    role: str = ROLE_MEMBER
    settings: Optional[dict] = None
    secrets: Optional[dict] = None
    image_generator_id: Optional[uuid.UUID] = None
    search_engine_id: Optional[uuid.UUID] = None
    embedding_id: Optional[uuid.UUID] = None
    llm_id: Optional[uuid.UUID] = None
    fast_llm_id: Optional[uuid.UUID] = None
    sandbox_provider_id: Optional[uuid.UUID] = None


class UserCreate(UserBase):
    password: str
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    copy_owner_runtime_ids: bool = False
    copy_owner_module_secrets: bool = False


class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserShort(UserBase):
    """Короткая версия пользователя без дат"""

    id: uuid.UUID
    is_synthetic: bool = False

    def __hash__(self):
        def _freeze(value):
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, uuid.UUID):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
            if isinstance(value, (list, tuple, set, frozenset)):
                return tuple(_freeze(v) for v in value)
            return str(value)

        return hash(
            (
                str(self.id),
                self.email,
                self.is_active,
                self.is_superuser,
                self.role,
                _freeze(self.settings),
                _freeze(self.secrets),
                _freeze(self.image_generator_id),
                _freeze(self.search_engine_id),
                _freeze(self.embedding_id),
                _freeze(self.llm_id),
                _freeze(self.fast_llm_id),
                _freeze(self.sandbox_provider_id),
            )
        )

    class Config:
        from_attributes = True


class FilledSecretStatus(BaseModel):
    filled: bool


class UserSelfResponse(UserBase):
    id: uuid.UUID
    secrets: dict[str, str | FilledSecretStatus] | None = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Схема для частичного обновления полей пользователя."""

    model_config = ConfigDict(extra="forbid")

    settings: dict | None = None
    secrets: dict | None = None
    llm_id: uuid.UUID | None = None
    fast_llm_id: uuid.UUID | None = None
    image_generator_id: uuid.UUID | None = None
    search_engine_id: uuid.UUID | None = None
    embedding_id: uuid.UUID | None = None
    sandbox_provider_id: uuid.UUID | None = None


class AdminUserUpdate(BaseModel):
    """Схема для частичного админ-обновления пользователя."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    password: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    role: Literal["owner", "admin", "member"] | None = None
    experimental_mode: bool | None = None


# ============ Repository ============


class UserRepository:
    """
    Repository для работы с пользователями в БД.
    Все методы работы с БД сосредоточены здесь.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(user_id: uuid.UUID) -> str:
        return f"user:ctx:{user_id}"

    @staticmethod
    async def get_from_cache(user_id: uuid.UUID) -> UserShort | None:
        cached = await cache.get(UserRepository.cache_key(user_id))
        if cached is None:
            return None
        return UserShort.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        user_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> UserShort | None:
        cached = await cls.get_from_cache(user_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id(user_id, use_cache=False)

    @staticmethod
    async def invalidate_cache(user_id: uuid.UUID) -> None:
        await cache.delete(UserRepository.cache_key(user_id))
        # Кэш доступных модулей зависит от user-настроек (secrets, embedding_id и т.п.) —
        # инвалидируем вместе с user-кэшем.
        await cache.delete(f"modules:user:{user_id}")

    @staticmethod
    def _to_short(user: User) -> UserShort:
        return UserShort.model_validate(user)

    async def _get_model_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Получить пользователя по email"""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        user_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> UserShort | None:
        """Получить пользователя по UUID (cache-first short user)."""
        if use_cache:
            cached = await self.get_from_cache(user_id)
            if cached is not None:
                return cached

        user = await self._get_model_by_id(user_id)
        if user is None:
            return None

        ctx = self._to_short(user)
        key = self.cache_key(user_id)
        await cache.set(key, ctx.model_dump(), expire="5m")
        return ctx

    async def create(
        self,
        email: str,
        hashed_password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_active: bool = True,
        is_superuser: bool = False,
        *,
        role: str | None = None,
        commit: bool = True,
    ) -> User:
        """Создать нового пользователя.

        role — источник правды; если не передана, выводится из is_superuser
        (True → admin). is_superuser всегда синхронизируется с ролью.
        """
        resolved_role = role or (ROLE_ADMIN if is_superuser else ROLE_MEMBER)
        if resolved_role not in ROLES:
            raise ValueError(f"Unknown role: {resolved_role}")
        user = User(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
            is_superuser=role_implies_superuser(resolved_role),
            role=resolved_role,
        )
        self.db.add(user)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(
        self,
        user: User,
        **kwargs,
    ) -> User:
        """Обновить данные пользователя"""
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)
        await self.invalidate_cache(user.id)
        return user

    async def update_settings(
        self,
        user_id: uuid.UUID,
        settings: dict,
    ) -> UserShort:
        """Обновить настройки пользователя (merge с существующими)"""
        user = await self._get_model_by_id(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        current = dict(user.settings or {})
        current.update(settings)
        user.settings = current
        await self.db.commit()
        await self.db.refresh(user)

        ctx = self._to_short(user)
        await self.invalidate_cache(user.id)
        await cache.set(
            self.cache_key(user.id),
            ctx.model_dump(),
            expire="5m",
        )
        return ctx

    async def delete(self, user: User) -> None:
        """Удалить пользователя"""
        await self.db.delete(user)
        await self.db.commit()
        await self.invalidate_cache(user.id)

    async def exists_by_email(self, email: str) -> bool:
        """Проверить существует ли пользователь с таким email"""
        user = await self.get_by_email(email)
        return user is not None

    async def get_all(
        self,
        skip: int = 0,
        limit: int | None = None,
        only_active: bool = False,
    ) -> list[User]:
        """Получить список пользователей"""
        query = select(User)
        if only_active:
            query = query.where(User.is_active.is_(True))
        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)
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
        user = await self._get_model_by_id(user_id)
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
