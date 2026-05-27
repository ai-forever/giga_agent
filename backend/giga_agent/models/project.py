import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base


class Project(Base):
    """Проект — группа тредов с общими инструкциями и knowledge-коллекцией."""

    __tablename__ = "core_projects"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_project_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core_rag_collections.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=1024)
    instructions: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=1024)
    instructions: str | None = None


class ProjectResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None = None
    instructions: str | None = None
    collection_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def get_for_owner(
        self, project_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Project | None:
        result = await self.db.execute(
            select(Project).where(
                Project.id == project_id, Project.owner_id == owner_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[Project]:
        result = await self.db.execute(
            select(Project)
            .where(Project.owner_id == owner_id)
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        collection_id: uuid.UUID | None = None,
    ) -> Project | None:
        """Create a project. Returns None on duplicate owner+name."""
        project = Project(
            owner_id=owner_id,
            name=name,
            description=description,
            instructions=instructions,
            collection_id=collection_id,
        )
        self.db.add(project)
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            details = str(getattr(e, "orig", e))
            if (
                "uq_project_owner_name" in details
                or "core_projects.owner_id, core_projects.name" in details
            ):
                return None
            raise
        await self.db.refresh(project)
        return project

    async def update(self, project: Project, **kwargs) -> Project:
        for key, value in kwargs.items():
            if value is not None and hasattr(project, key):
                setattr(project, key, value)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        await self.db.delete(project)
        await self.db.commit()

    async def delete_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(
            delete(Project).where(Project.owner_id == owner_id)
        )
        await self.db.commit()
        return int(result.rowcount or 0)
