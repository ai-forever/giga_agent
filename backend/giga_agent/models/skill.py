import uuid
from datetime import datetime
from enum import Enum
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT


# ============ Enums ============


class SkillSourceType(str, Enum):
    BUILTIN = "builtin"
    UPLOAD = "upload"
    LOCAL_DIR = "local_dir"
    GITHUB = "github"


# ============ SQLAlchemy Model ============


class Skill(Base):
    """Скилл пользователя — метаданные + ссылка на файлы в sandbox."""

    __tablename__ = "core_skills"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_skill_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SkillSourceType.UPLOAD
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON_VARIANT(), default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


# ============ Pydantic Schemas ============


class SkillSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_enabled: bool
    source_type: str
    created_at: datetime
    is_readonly: bool = False
    can_toggle: bool = True

    class Config:
        from_attributes = True


class SkillResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str
    source_type: str
    source_url: str | None = None
    storage_path: str
    is_enabled: bool
    metadata_: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class SkillFile(BaseModel):
    relative_path: str
    sandbox_path: str


class SkillActivation(BaseModel):
    name: str
    sandbox_path: str
    body: str
    files: list[SkillFile]


class BuiltinSkillInfo(BaseModel):
    name: str
    description: str
    is_installed: bool = False


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    source_type: SkillSourceType = SkillSourceType.UPLOAD


class SkillUpdate(BaseModel):
    is_enabled: bool | None = None


# ============ Repository ============


class SkillRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        result = await self.db.execute(select(Skill).where(Skill.id == skill_id))
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: uuid.UUID) -> list[Skill]:
        result = await self.db.execute(
            select(Skill)
            .where(Skill.owner_id == owner_id)
            .order_by(Skill.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_enabled_by_owner(self, owner_id: uuid.UUID) -> list[Skill]:
        result = await self.db.execute(
            select(Skill)
            .where(Skill.owner_id == owner_id, Skill.is_enabled == True)  # noqa: E712
            .order_by(Skill.name)
        )
        return list(result.scalars().all())

    async def get_by_owner_and_name(
        self, owner_id: uuid.UUID, name: str
    ) -> Skill | None:
        result = await self.db.execute(
            select(Skill).where(Skill.owner_id == owner_id, Skill.name == name)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        description: str,
        source_type: str,
        storage_path: str,
        source_url: str | None = None,
        is_enabled: bool = True,
        metadata_: dict | None = None,
    ) -> Skill | None:
        """Create a skill record. Returns None on duplicate owner+name."""
        skill = Skill(
            owner_id=owner_id,
            name=name,
            description=description,
            source_type=source_type,
            storage_path=storage_path,
            source_url=source_url,
            is_enabled=is_enabled,
            metadata_=metadata_ or {},
        )
        self.db.add(skill)
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            details = str(getattr(e, "orig", e))
            if "uq_skill_owner_name" in details:
                return None
            raise
        await self.db.refresh(skill)
        return skill

    async def update(self, skill: Skill, **kwargs) -> Skill:
        for key, value in kwargs.items():
            if value is not None and hasattr(skill, key):
                setattr(skill, key, value)
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def delete(self, skill: Skill) -> None:
        await self.db.delete(skill)
        await self.db.commit()

    async def delete_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(delete(Skill).where(Skill.owner_id == owner_id))
        await self.db.commit()
        return int(result.rowcount or 0)

    async def delete_local_dir_not_in(
        self, owner_id: uuid.UUID, names: set[str]
    ) -> int:
        """Delete LOCAL_DIR skills whose names are not in the given set."""
        query = (
            delete(Skill)
            .where(Skill.owner_id == owner_id)
            .where(Skill.source_type == SkillSourceType.LOCAL_DIR)
        )
        if names:
            query = query.where(Skill.name.notin_(names))
        result = await self.db.execute(query)
        await self.db.commit()
        return int(result.rowcount or 0)
