from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT


class AgentProfile(Base):
    """Per-user custom agent or settings/bindings for a built-in agent."""

    __tablename__ = "core_agent_profiles"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "builtin_ref", name="uq_core_agent_profile_builtin_owner"
        ),
        CheckConstraint(
            "source IN ('custom', 'builtin_override')",
            name="ck_core_agent_profiles_source",
        ),
        CheckConstraint(
            "(source = 'custom' AND builtin_ref IS NULL) OR "
            "(source = 'builtin_override' AND builtin_ref IS NOT NULL)",
            name="ck_core_agent_profiles_builtin_ref",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_core_agent_profiles_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    builtin_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[list] = mapped_column(JSON_VARIANT(), default=list)
    modules: Mapped[list] = mapped_column(JSON_VARIANT(), default=list)
    tool_policy: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    examples: Mapped[list] = mapped_column(JSON_VARIANT(), default=list)
    llm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core_llms.id", ondelete="SET NULL"), nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class AgentSkillBinding(Base):
    __tablename__ = "core_agent_skill_bindings"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "requirement_name", name="uq_agent_skill_requirement"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core_skills.id", ondelete="SET NULL"), nullable=True
    )
    resolved_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AgentConnectorBinding(Base):
    __tablename__ = "core_agent_connector_bindings"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "catalog_id", name="uq_agent_connector_requirement"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core_mcp_servers.id", ondelete="SET NULL"), nullable=True
    )


class AgentMcpBinding(Base):
    """Direct MCP server selection for a custom sub-agent.

    ``AgentConnectorBinding`` is intentionally kept for built-in manifest
    requirements, which still use catalog ids. Custom profiles bind directly
    to the user's accessible server records and never persist catalog ids.
    """

    __tablename__ = "core_agent_mcp_bindings"
    __table_args__ = (
        UniqueConstraint("profile_id", "mcp_server_id", name="uq_agent_mcp_binding"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("core_mcp_servers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class AgentProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    prompt: str = Field(min_length=1)
    icon: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    tool_policy: dict[str, Any] = Field(
        default_factory=lambda: {"allowed_effects": ["read"]}
    )
    examples: list[str] = Field(default_factory=list)
    llm_id: uuid.UUID | None = None
    is_enabled: bool = True


class AgentProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=1024)
    prompt: str | None = Field(default=None, min_length=1)
    icon: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None
    modules: list[str] | None = None
    tool_policy: dict[str, Any] | None = None
    examples: list[str] | None = None
    llm_id: uuid.UUID | None = None
    is_enabled: bool | None = None


class AgentBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_id: uuid.UUID | None = None
    skills: dict[str, uuid.UUID] = Field(default_factory=dict)
    connectors: dict[str, uuid.UUID] = Field(default_factory=dict)


class AgentProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, profile_id: uuid.UUID) -> AgentProfile | None:
        return await self.db.get(AgentProfile, profile_id)

    async def get_for_owner(
        self, profile_id: uuid.UUID, owner_id: uuid.UUID
    ) -> AgentProfile | None:
        result = await self.db.execute(
            select(AgentProfile).where(
                AgentProfile.id == profile_id, AgentProfile.owner_id == owner_id
            )
        )
        return result.scalar_one_or_none()

    async def get_builtin_override(
        self, owner_id: uuid.UUID, builtin_ref: str
    ) -> AgentProfile | None:
        result = await self.db.execute(
            select(AgentProfile).where(
                AgentProfile.owner_id == owner_id,
                AgentProfile.builtin_ref == builtin_ref,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_owner(self, owner_id: uuid.UUID) -> list[AgentProfile]:
        result = await self.db.execute(
            select(AgentProfile)
            .where(AgentProfile.owner_id == owner_id)
            .order_by(AgentProfile.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_custom(
        self, owner_id: uuid.UUID, data: AgentProfileCreate
    ) -> AgentProfile:
        row = AgentProfile(
            owner_id=owner_id,
            source="custom",
            **data.model_dump(),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def ensure_builtin_override(
        self, owner_id: uuid.UUID, builtin_ref: str
    ) -> AgentProfile:
        existing = await self.get_builtin_override(owner_id, builtin_ref)
        if existing is not None:
            return existing
        row = AgentProfile(
            owner_id=owner_id,
            source="builtin_override",
            builtin_ref=builtin_ref,
            is_enabled=True,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def update(self, row: AgentProfile, values: dict[str, Any]) -> AgentProfile:
        for key, value in values.items():
            if hasattr(row, key):
                setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, row: AgentProfile) -> None:
        await self.db.execute(
            delete(AgentSkillBinding).where(AgentSkillBinding.profile_id == row.id)
        )
        await self.db.execute(
            delete(AgentConnectorBinding).where(
                AgentConnectorBinding.profile_id == row.id
            )
        )
        await self.db.execute(
            delete(AgentMcpBinding).where(AgentMcpBinding.profile_id == row.id)
        )
        await self.db.delete(row)
        await self.db.commit()

    async def skill_bindings(self, profile_id: uuid.UUID) -> list[AgentSkillBinding]:
        result = await self.db.execute(
            select(AgentSkillBinding).where(AgentSkillBinding.profile_id == profile_id)
        )
        return list(result.scalars().all())

    async def connector_bindings(
        self, profile_id: uuid.UUID
    ) -> list[AgentConnectorBinding]:
        result = await self.db.execute(
            select(AgentConnectorBinding).where(
                AgentConnectorBinding.profile_id == profile_id
            )
        )
        return list(result.scalars().all())

    async def mcp_bindings(self, profile_id: uuid.UUID) -> list[AgentMcpBinding]:
        result = await self.db.execute(
            select(AgentMcpBinding).where(AgentMcpBinding.profile_id == profile_id)
        )
        return list(result.scalars().all())

    async def replace_bindings(
        self,
        profile_id: uuid.UUID,
        *,
        skills: list[dict[str, Any]],
        connectors: list[dict[str, Any]],
    ) -> None:
        await self.db.execute(
            delete(AgentSkillBinding).where(AgentSkillBinding.profile_id == profile_id)
        )
        await self.db.execute(
            delete(AgentConnectorBinding).where(
                AgentConnectorBinding.profile_id == profile_id
            )
        )
        self.db.add_all(
            [AgentSkillBinding(profile_id=profile_id, **item) for item in skills]
        )
        self.db.add_all(
            [
                AgentConnectorBinding(profile_id=profile_id, **item)
                for item in connectors
            ]
        )
        await self.db.commit()

    async def replace_custom_bindings(
        self,
        profile_id: uuid.UUID,
        *,
        skills: list[dict[str, Any]],
        mcp_server_ids: list[uuid.UUID],
    ) -> None:
        """Replace only the capability bindings owned by a custom profile."""
        await self.db.execute(
            delete(AgentSkillBinding).where(AgentSkillBinding.profile_id == profile_id)
        )
        await self.db.execute(
            delete(AgentMcpBinding).where(AgentMcpBinding.profile_id == profile_id)
        )
        self.db.add_all(
            [AgentSkillBinding(profile_id=profile_id, **item) for item in skills]
        )
        self.db.add_all(
            [
                AgentMcpBinding(profile_id=profile_id, mcp_server_id=server_id)
                for server_id in dict.fromkeys(mcp_server_ids)
            ]
        )
        await self.db.commit()
