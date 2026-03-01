import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import (
    String,
    DateTime,
    Uuid,
    ForeignKey,
    Integer,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, joinedload
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)

SANDBOXPAIR_CACHE_TTL = "60s"


# ============ Enums ============


class SandboxProviderType(str, Enum):
    """Известные типы провайдеров. Не ограничивает — type хранится как str."""

    E2B = "e2b"
    DAYTONA = "daytona"
    MODAL = "modal"
    LOCAL_DOCKER = "local_docker"


class SandboxStatus(str, Enum):
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# ============ SQLAlchemy Models ============


class SandboxProvider(Base):
    """
    Подключение к сервису виртуальных окружений.
    Создаётся пользователем (владельцем).
    """

    __tablename__ = "core_sandbox_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Настройки подключения к провайдеру (API key, endpoint, S3 creds и т.д.)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)

    # Таймаут простоя для всех sandbox'ов этого провайдера (секунды)
    idle_timeout: Mapped[int] = mapped_column(Integer, default=3600)

    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    # Relationships
    sandboxes: Mapped[list["Sandbox"]] = relationship(
        "Sandbox", back_populates="provider", cascade="all, delete-orphan"
    )


class Sandbox(Base):
    """
    Конкретный экземпляр песочницы пользователя.
    Один пользователь — один sandbox на провайдера.
    """

    __tablename__ = "core_sandboxes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_sandbox_providers.id"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=SandboxStatus.STOPPED
    )
    # ID ресурса в системе провайдера (container_id, sandbox_id, workspace_id и т.д.)
    external_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )

    # Настройки инстанса — переопределение image, env vars, ресурсов и т.д.
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)

    # === Tracking активности ===
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    # Один sandbox на юзера в рамках одного провайдера
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "provider_id", name="uq_sandbox_owner_provider"
        ),
    )

    # Relationships
    provider: Mapped["SandboxProvider"] = relationship(
        "SandboxProvider", back_populates="sandboxes"
    )


# ============ Pydantic Schemas ============


class SandboxProviderBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    idle_timeout: int = 3600
    is_active: bool = True


class SandboxProviderCreate(SandboxProviderBase):
    """
    При создании провайдера settings валидируются через
    SandboxRegistry.validate_settings(type, settings).
    """

    permissions: ResourcePermissionsPayload | None = None


class SandboxProviderUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    idle_timeout: Optional[int] = None
    is_active: Optional[bool] = None


class SandboxProviderResponse(SandboxProviderBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SandboxSettings(BaseModel):
    """Настройки конкретного инстанса (переопределения)."""

    image: Optional[str] = None
    env_vars: Optional[dict[str, str]] = None
    extra: Optional[dict[str, Any]] = None


class SandboxBase(BaseModel):
    settings: SandboxSettings = Field(default_factory=SandboxSettings)


class SandboxCreate(SandboxBase):
    provider_id: uuid.UUID


class SandboxUpdate(BaseModel):
    settings: Optional[SandboxSettings] = None


class SandboxResponse(SandboxBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_id: uuid.UUID
    status: str
    external_id: Optional[str] = None
    last_activity_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SandboxProviderInstanceResponse(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    owner_id: uuid.UUID
    owner_email: str | None = None
    status: str
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    can_stop: bool = False


class SandboxProviderSnapshot(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    idle_timeout: int = 3600
    is_active: bool = True
    updated_at: Optional[datetime] = None


class SandboxSnapshot(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_id: uuid.UUID
    status: str
    external_id: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class SandboxPairSnapshot(BaseModel):
    provider: SandboxProviderSnapshot
    sandbox: SandboxSnapshot


# ============ Repository ============


class SandboxProviderRepository(ACLResourceRepositoryMixin[SandboxProvider]):
    """Repository для работы с провайдерами песочниц."""
    resource_model = SandboxProvider
    resource_type = "sandbox"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, provider_id: uuid.UUID) -> SandboxProvider | None:
        """Получить провайдера по ID."""
        result = await self.db.execute(
            select(SandboxProvider).where(SandboxProvider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[SandboxProvider]:
        """Получить все провайдеры пользователя."""
        query = select(SandboxProvider).where(
            SandboxProvider.owner_id == owner_id
        )
        if only_active:
            query = query.where(SandboxProvider.is_active == True)  # noqa: E712
        query = query.order_by(SandboxProvider.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[SandboxProvider]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_with_access_for_user(
        self,
        provider_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[SandboxProvider, bool, bool] | None:
        return await super().get_by_id_with_access_for_user(
            provider_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

    async def get_by_id_readable(
        self,
        provider_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> SandboxProvider | None:
        row = await self.get_by_id_with_access_for_user(
            provider_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        provider, can_read, _ = row
        if not can_read:
            return None
        return provider

    async def get_by_id_writable(
        self,
        provider_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> SandboxProvider | None:
        row = await self.get_by_id_with_access_for_user(
            provider_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        provider, _, can_edit = row
        if not can_edit:
            return None
        return provider

    async def get_writable_ids_for_user(
        self,
        *,
        user_id: uuid.UUID,
        resource_ids: list[uuid.UUID],
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        return await ResourcePermissionRepository(self.db).list_resource_ids_with_access(
            user_id=user_id,
            resource_type="sandbox",
            resource_ids=resource_ids,
            permission="write",
            user_group_ids=user_group_ids,
        )

    async def get_by_owner_and_type(
        self,
        owner_id: uuid.UUID,
        provider_type: str,
    ) -> SandboxProvider | None:
        """Получить провайдера по владельцу и типу."""
        result = await self.db.execute(
            select(SandboxProvider)
            .where(SandboxProvider.owner_id == owner_id)
            .where(SandboxProvider.type == provider_type)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        owner_id: uuid.UUID,
        provider_type: str,
        name: Optional[str] = None,
        settings: Optional[dict] = None,
        idle_timeout: int = 3600,
        is_active: bool = True,
    ) -> SandboxProvider:
        """Создать нового провайдера."""
        provider = SandboxProvider(
            owner_id=owner_id,
            type=provider_type,
            name=name,
            settings=settings or {},
            idle_timeout=idle_timeout,
            is_active=is_active,
        )
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def update(
        self,
        provider: SandboxProvider,
        **kwargs: Any,
    ) -> SandboxProvider:
        """Обновить провайдера."""
        for key, value in kwargs.items():
            if hasattr(provider, key) and value is not None:
                setattr(provider, key, value)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def delete(self, provider: SandboxProvider) -> None:
        """Удалить провайдера и все связанные sandbox'ы."""
        await ResourcePermissionRepository(self.db).revoke_all_for_resource(
            resource_type="sandbox",
            resource_id=provider.id,
            no_commit=True,
        )
        await self.db.delete(provider)
        await self.db.commit()

    @staticmethod
    def to_response(
        provider: SandboxProvider,
        *,
        can_edit: bool = False,
    ) -> SandboxProviderResponse:
        """Преобразовать в Pydantic response."""
        response = SandboxProviderResponse.model_validate(provider)
        response.can_edit = can_edit
        return response


class SandboxRepository:
    """Repository для работы с песочницами."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(owner_id: uuid.UUID, provider_id: uuid.UUID) -> str:
        return f"sandboxpair:owner:{owner_id}:provider:{provider_id}"

    @staticmethod
    def cache_key_default(owner_id: uuid.UUID) -> str:
        return f"sandboxpair:owner:{owner_id}:default"

    @staticmethod
    def to_pair_snapshot(
        provider: SandboxProvider,
        sandbox: Sandbox,
    ) -> SandboxPairSnapshot:
        return SandboxPairSnapshot(
            provider=SandboxProviderSnapshot(
                id=provider.id,
                owner_id=provider.owner_id,
                type=provider.type,
                name=provider.name,
                settings=provider.settings or {},
                idle_timeout=provider.idle_timeout,
                is_active=provider.is_active,
                updated_at=provider.updated_at,
            ),
            sandbox=SandboxSnapshot(
                id=sandbox.id,
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
                status=sandbox.status,
                external_id=sandbox.external_id,
                settings=sandbox.settings or {},
                updated_at=sandbox.updated_at,
            ),
        )

    @staticmethod
    async def cache_set_pair(
        *,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
        snapshot: SandboxPairSnapshot,
        is_default: bool,
    ) -> None:
        await cache.set(
            SandboxRepository.cache_key(owner_id, provider_id),
            snapshot.model_dump(),
            expire=SANDBOXPAIR_CACHE_TTL,
        )
        if is_default:
            await cache.set(
                SandboxRepository.cache_key_default(owner_id),
                snapshot.model_dump(),
                expire=SANDBOXPAIR_CACHE_TTL,
            )

    @staticmethod
    async def cache_get_pair(
        *,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None,
    ) -> SandboxPairSnapshot | None:
        key = (
            SandboxRepository.cache_key_default(owner_id)
            if provider_id is None
            else SandboxRepository.cache_key(owner_id, provider_id)
        )
        cached = await cache.get(key)
        if cached is None:
            return None
        return SandboxPairSnapshot.model_validate(cached)

    @staticmethod
    async def cache_invalidate_pair(
        *,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
    ) -> None:
        await cache.delete(SandboxRepository.cache_key(owner_id, provider_id))
        # Default key may point to this provider; safest to delete it too.
        await cache.delete(SandboxRepository.cache_key_default(owner_id))

    async def get_by_id(self, sandbox_id: uuid.UUID) -> Sandbox | None:
        """Получить sandbox по ID."""
        result = await self.db.execute(
            select(Sandbox).where(Sandbox.id == sandbox_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_provider(
        self, sandbox_id: uuid.UUID
    ) -> Sandbox | None:
        """Получить sandbox по ID с подгруженным провайдером."""
        result = await self.db.execute(
            select(Sandbox)
            .where(Sandbox.id == sandbox_id)
            .options(joinedload(Sandbox.provider))
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
    ) -> list[Sandbox]:
        """Получить все sandbox'ы пользователя."""
        query = (
            select(Sandbox)
            .where(Sandbox.owner_id == owner_id)
            .order_by(Sandbox.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_owner_and_provider(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
    ) -> Sandbox | None:
        """Получить sandbox пользователя для конкретного провайдера."""
        result = await self.db.execute(
            select(Sandbox)
            .where(Sandbox.owner_id == owner_id)
            .where(Sandbox.provider_id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider(
        self,
        provider_id: uuid.UUID,
    ) -> list[Sandbox]:
        """Получить все sandbox'ы провайдера."""
        query = (
            select(Sandbox)
            .where(Sandbox.provider_id == provider_id)
            .order_by(Sandbox.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_provider_and_id(
        self,
        provider_id: uuid.UUID,
        sandbox_id: uuid.UUID,
    ) -> Sandbox | None:
        """Получить sandbox по ID в рамках провайдера."""
        result = await self.db.execute(
            select(Sandbox)
            .where(Sandbox.provider_id == provider_id)
            .where(Sandbox.id == sandbox_id)
        )
        return result.scalar_one_or_none()

    async def get_idle_sandboxes(self) -> list[Sandbox]:
        """
        Найти все запущенные sandbox'ы, превысившие idle timeout.
        Фильтрация в Python для кросс-платформенности (SQLite + Postgres).
        """
        result = await self.db.execute(
            select(Sandbox)
            .options(joinedload(Sandbox.provider))
            .where(Sandbox.status == SandboxStatus.RUNNING)
            .where(Sandbox.last_activity_at.isnot(None))
        )
        sandboxes = result.scalars().all()
        now = datetime.utcnow()

        return [
            s
            for s in sandboxes
            if (now - s.last_activity_at).total_seconds()
            > s.provider.idle_timeout
        ]

    async def create(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
        settings: Optional[dict] = None,
    ) -> Sandbox:
        """Создать новый sandbox."""
        sandbox = Sandbox(
            owner_id=owner_id,
            provider_id=provider_id,
            settings=settings or {},
        )
        self.db.add(sandbox)
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def update(
        self,
        sandbox: Sandbox,
        **kwargs: Any,
    ) -> Sandbox:
        """Обновить sandbox."""
        for key, value in kwargs.items():
            if hasattr(sandbox, key) and value is not None:
                setattr(sandbox, key, value)
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        """Обновить время последней активности."""
        sandbox = await self.get_by_id(sandbox_id)
        if sandbox:
            sandbox.last_activity_at = datetime.utcnow()
            await self.db.commit()

    async def set_status(
        self,
        sandbox: Sandbox,
        status: SandboxStatus,
    ) -> Sandbox:
        """Обновить статус sandbox'а с автоматическим проставлением timestamps."""
        sandbox.status = status
        now = datetime.utcnow()

        if status == SandboxStatus.RUNNING:
            sandbox.started_at = now
            sandbox.last_activity_at = now
            sandbox.stopped_at = None
        elif status in (SandboxStatus.STOPPED, SandboxStatus.ERROR):
            sandbox.stopped_at = now

        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def delete(self, sandbox: Sandbox) -> None:
        """Удалить sandbox."""
        await self.db.delete(sandbox)
        await self.db.commit()

    @staticmethod
    def to_response(sandbox: Sandbox) -> SandboxResponse:
        """Преобразовать в Pydantic response."""
        return SandboxResponse.model_validate(sandbox)
