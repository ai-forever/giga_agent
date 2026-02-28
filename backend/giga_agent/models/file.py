import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base
from giga_agent.models.resource_permission import ResourcePermissionRepository


# ============ SQLAlchemy Model ============


class File(Base):
    """Файл, загруженный в sandbox пользователя."""

    __tablename__ = "core_files"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "provider_id",
            "sandbox_path",
            name="uq_file_owner_provider_path",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_sandbox_providers.id"), nullable=False, index=True
    )
    sandbox_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


# ============ Pydantic Schemas ============


FileType = Literal[
    "image",
    "plotly_graph",
    "html",
    "text",
    "audio",
    "video",
    "other",
]


class FileBase(BaseModel):
    sandbox_path: str
    original_name: str
    file_type: FileType
    size: int = Field(..., ge=0)


class FileCreate(FileBase):
    provider_id: uuid.UUID


class FileUpdate(BaseModel):
    sandbox_path: Optional[str] = None
    original_name: Optional[str] = None
    file_type: Optional[FileType] = None
    size: Optional[int] = Field(default=None, ge=0)


class FileResponse(FileBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_id: uuid.UUID
    sandbox_path: str
    original_name: str
    size: int
    file_type: FileType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Repository ============


class FileRepository:
    """Repository для работы с файлами sandbox."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, file_id: uuid.UUID) -> File | None:
        """Получить файл по ID."""
        result = await self.db.execute(select(File).where(File.id == file_id))
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Получить файлы пользователя с optional фильтром по провайдеру."""
        query = select(File).where(File.owner_id == owner_id)
        if provider_id is not None:
            query = query.where(File.provider_id == provider_id)
        query = query.order_by(File.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        provider_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[File]:
        permission_repo = ResourcePermissionRepository(self.db)
        access_clause = await permission_repo.build_access_clause(
            File,
            user_id=user_id,
            resource_type="file",
            permission="read",
            user_group_ids=user_group_ids,
        )
        query = select(File).where(access_clause)
        if provider_id is not None:
            query = query.where(File.provider_id == provider_id)
        query = query.order_by(File.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_owner_provider_path(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
        sandbox_path: str,
    ) -> File | None:
        """Получить файл по уникальному ключу owner+provider+path."""
        result = await self.db.execute(
            select(File)
            .where(File.owner_id == owner_id)
            .where(File.provider_id == provider_id)
            .where(File.sandbox_path == sandbox_path)
        )
        return result.scalar_one_or_none()

    async def get_by_owner_path(
        self,
        owner_id: uuid.UUID,
        sandbox_path: str,
    ) -> File | None:
        """
        Получить файл по owner+path без явного provider.

        Если найдено несколько записей (разные provider), возвращает самую новую.
        """
        result = await self.db.execute(
            select(File)
            .where(File.owner_id == owner_id)
            .where(File.sandbox_path == sandbox_path)
            .order_by(File.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id_readable(
        self,
        file_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> File | None:
        permission_repo = ResourcePermissionRepository(self.db)
        access_clause = await permission_repo.build_access_clause(
            File,
            user_id=user_id,
            resource_type="file",
            permission="read",
            user_group_ids=user_group_ids,
        )
        result = await self.db.execute(select(File).where(File.id == file_id).where(access_clause))
        return result.scalar_one_or_none()

    async def get_by_path_readable(
        self,
        *,
        user_id: uuid.UUID,
        sandbox_path: str,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> File | None:
        permission_repo = ResourcePermissionRepository(self.db)
        access_clause = await permission_repo.build_access_clause(
            File,
            user_id=user_id,
            resource_type="file",
            permission="read",
            user_group_ids=user_group_ids,
        )
        result = await self.db.execute(
            select(File)
            .where(File.sandbox_path == sandbox_path)
            .where(access_clause)
            .order_by(File.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_path_any_owner(self, *, sandbox_path: str) -> File | None:
        result = await self.db.execute(
            select(File)
            .where(File.sandbox_path == sandbox_path)
            .order_by(File.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
        sandbox_path: str,
        original_name: str,
        file_type: FileType = "other",
        size: int = 0,
    ) -> File | None:
        """
        Создать запись файла.

        Возвращает None, если запись с таким owner+provider+path уже существует.
        """
        if size < 0:
            raise ValueError("size must be >= 0")
        original_name = (original_name or "").strip()
        if not original_name:
            raise ValueError("original_name must not be empty")
        file = File(
            owner_id=owner_id,
            provider_id=provider_id,
            sandbox_path=sandbox_path,
            original_name=original_name,
            file_type=file_type,
            size=size,
        )
        self.db.add(file)
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            details = str(getattr(e, "orig", e))
            if "uq_file_owner_provider_path" in details or (
                "core_files.owner_id, core_files.provider_id, core_files.sandbox_path"
                in details
            ):
                return None
            raise
        await self.db.refresh(file)
        return file

    async def delete(self, file: File) -> None:
        """Удалить запись файла."""
        await self.db.delete(file)
        await self.db.commit()

    @staticmethod
    def to_response(file: File) -> FileResponse:
        """Преобразовать ORM-модель в Pydantic response."""
        return FileResponse.model_validate(file)
