import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models.users import User, UserShort


class Group(Base):
    __tablename__ = "core_groups"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_core_groups_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_groups_owner_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON_VARIANT(), nullable=True, default=None)
    permissions: Mapped[dict | None] = mapped_column(
        JSON_VARIANT(), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class GroupMember(Base):
    __tablename__ = "core_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_groups.id", name="fk_core_group_members_group_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_group_members_user_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class GroupBase(BaseModel):
    name: str
    description: str | None = None
    data: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None


class GroupCreate(GroupBase):
    owner_id: uuid.UUID | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    data: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None


class GroupResponse(GroupBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GroupMemberAddRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class GroupIdsByUserResponse(BaseModel):
    user_id: uuid.UUID
    group_ids: list[uuid.UUID]


class GroupRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        description: str | None = None,
        data: dict[str, Any] | None = None,
        permissions: dict[str, Any] | None = None,
    ) -> Group:
        group = Group(
            owner_id=owner_id,
            name=name,
            description=description,
            data=data,
            permissions=permissions,
        )
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def list_all(self) -> list[Group]:
        result = await self.db.execute(select(Group).order_by(Group.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_id(self, group_id: uuid.UUID) -> Group | None:
        result = await self.db.execute(select(Group).where(Group.id == group_id))
        return result.scalar_one_or_none()

    async def get_group_ids_by_user_id(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.db.execute(
            select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        )
        return [row[0] for row in result.all()]

    async def get_existing_group_ids(self, group_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        normalized_group_ids = list(dict.fromkeys(group_ids))
        if not normalized_group_ids:
            return []

        result = await self.db.execute(select(Group.id).where(Group.id.in_(normalized_group_ids)))
        return [row[0] for row in result.all()]

    async def get_group_users(self, group_id: uuid.UUID) -> list[UserShort]:
        result = await self.db.execute(
            select(User).join(GroupMember, GroupMember.user_id == User.id).where(
                GroupMember.group_id == group_id
            )
        )
        users = list(result.scalars().all())
        return [UserShort.model_validate(user) for user in users]

    async def update(self, group: Group, **kwargs: Any) -> Group:
        for key, value in kwargs.items():
            if hasattr(group, key) and value is not None:
                setattr(group, key, value)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def add_users(
        self,
        group_id: uuid.UUID,
        user_ids: list[uuid.UUID],
        *,
        commit: bool = True,
    ) -> None:
        normalized_user_ids = list(dict.fromkeys(user_ids))
        if not normalized_user_ids:
            return

        existing_users_result = await self.db.execute(
            select(User.id).where(User.id.in_(normalized_user_ids))
        )
        existing_user_ids = {row[0] for row in existing_users_result.all()}
        if len(existing_user_ids) != len(normalized_user_ids):
            missing = [uid for uid in normalized_user_ids if uid not in existing_user_ids]
            missing_str = ", ".join(str(uid) for uid in missing)
            raise ValueError(f"Users not found: {missing_str}")

        existing_members_result = await self.db.execute(
            select(GroupMember.user_id).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id.in_(normalized_user_ids),
            )
        )
        existing_member_ids = {row[0] for row in existing_members_result.all()}

        for user_id in normalized_user_ids:
            if user_id in existing_member_ids:
                continue
            self.db.add(GroupMember(group_id=group_id, user_id=user_id))
        if commit:
            await self.db.commit()

    async def remove_user(self, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            return False

        await self.db.delete(membership)
        await self.db.commit()
        return True

    async def delete(self, group: Group) -> None:
        await self.db.delete(group)
        await self.db.commit()

    @staticmethod
    def to_response(group: Group) -> GroupResponse:
        return GroupResponse.model_validate(group)
