import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.llm.base import AvailableModel, ModelFetchError
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.connector import Connector  # noqa: F401
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)

# Ensure runtimes are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401


class LLM(Base):
    """Configured LLM model bound to a connector."""

    __tablename__ = "core_llms"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_llms_owner_id"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_connectors.id",
            name="fk_core_llms_connector_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parallel_calls: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    connector = relationship("Connector", lazy="joined")


class LLMSettings(BaseModel):
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    extra: Optional[dict[str, Any]] = None


class LLMBase(BaseModel):
    type: str
    connector_id: uuid.UUID
    model_id: str
    name: Optional[str] = None
    parallel_calls: int = 1
    settings: LLMSettings = Field(default_factory=LLMSettings)
    is_active: bool = True


class LLMCreate(LLMBase):
    permissions: ResourcePermissionsPayload | None = None


class LLMUpdate(BaseModel):
    type: Optional[str] = None
    connector_id: Optional[uuid.UUID] = None
    model_id: Optional[str] = None
    name: Optional[str] = None
    parallel_calls: Optional[int] = None
    settings: Optional[LLMSettings] = None
    is_active: Optional[bool] = None


class LLMResponse(LLMBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LLMContext(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    connector_id: uuid.UUID
    type: str
    model_id: str
    parallel_calls: int
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class LLMRepository(ACLResourceRepositoryMixin[LLM]):
    """Repository for LLM records and cacheable LLM config context."""
    resource_model = LLM
    resource_type = "llm"

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(llm_id: uuid.UUID) -> str:
        return f"llm:ctx:{llm_id}"

    @staticmethod
    async def invalidate_cache(llm_id: uuid.UUID) -> None:
        await cache.delete(LLMRepository.cache_key(llm_id))

    @staticmethod
    async def get_from_cache(
        llm_id: uuid.UUID,
    ) -> LLMContext | None:
        cached = await cache.get(LLMRepository.cache_key(llm_id))
        if cached is None:
            return None
        return LLMContext.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        llm_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> LLMContext | None:
        cached = await cls.get_from_cache(llm_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id_context(llm_id, use_cache=False)

    @classmethod
    async def get_cached_context_or_db(
        cls,
        llm_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> LLMContext | None:
        return await cls.get_cached_or_db(
            llm_id,
            session=session,
        )

    async def get_by_id(self, llm_id: uuid.UUID) -> LLM | None:
        result = await self.db.execute(select(LLM).where(LLM.id == llm_id))
        return result.scalar_one_or_none()

    async def get_by_id_context(
        self,
        llm_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> LLMContext | None:
        if use_cache:
            cached = await self.get_from_cache(llm_id)
            if cached is not None:
                return cached

        llm = await self.get_by_id(llm_id)
        if llm is None:
            return None

        context = LLMContext(
            id=llm.id,
            owner_id=llm.owner_id,
            connector_id=llm.connector_id,
            type=llm.type,
            model_id=llm.model_id,
            parallel_calls=llm.parallel_calls,
            settings=llm.settings or {},
            is_active=llm.is_active,
        )
        await cache.set(
            self.cache_key(llm_id),
            context.model_dump(mode="json"),
            expire="5m",
        )
        return context

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[LLM]:
        query = select(LLM).where(LLM.owner_id == owner_id)
        if only_active:
            query = query.where(LLM.is_active == True)  # noqa: E712
        query = query.order_by(LLM.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[LLM]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_with_access_for_user(
        self,
        llm_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[LLM, bool, bool] | None:
        return await super().get_by_id_with_access_for_user(
            llm_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

    async def get_by_id_readable(
        self,
        llm_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> LLM | None:
        row = await self.get_by_id_with_access_for_user(
            llm_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        llm, can_read, _ = row
        if not can_read:
            return None
        return llm

    async def get_by_id_writable(
        self,
        llm_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> LLM | None:
        row = await self.get_by_id_with_access_for_user(
            llm_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        llm, _, can_edit = row
        if not can_edit:
            return None
        return llm

    async def get_writable_ids_for_user(
        self,
        *,
        user_id: uuid.UUID,
        resource_ids: list[uuid.UUID],
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        return await ResourcePermissionRepository(self.db).list_resource_ids_with_access(
            user_id=user_id,
            resource_type="llm",
            resource_ids=resource_ids,
            permission="write",
            user_group_ids=user_group_ids,
        )

    async def get_by_connector(
        self,
        connector_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[LLM]:
        query = select(LLM).where(LLM.connector_id == connector_id)
        if only_active:
            query = query.where(LLM.is_active == True)  # noqa: E712
        query = query.order_by(LLM.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: uuid.UUID,
        llm_type: str,
        connector_id: uuid.UUID,
        model_id: str,
        name: Optional[str] = None,
        parallel_calls: int = 1,
        settings: Optional[dict[str, Any]] = None,
        is_active: bool = True,
    ) -> LLM:
        llm = LLM(
            owner_id=owner_id,
            type=llm_type,
            connector_id=connector_id,
            model_id=model_id,
            name=name,
            parallel_calls=parallel_calls,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(llm)
        await self.db.commit()
        await self.db.refresh(llm)
        await self.invalidate_cache(llm.id)
        return llm

    async def update(
        self,
        llm: LLM,
        **kwargs: Any,
    ) -> LLM:
        for key, value in kwargs.items():
            if hasattr(llm, key) and value is not None:
                setattr(llm, key, value)
        await self.db.commit()
        await self.db.refresh(llm)
        await self.invalidate_cache(llm.id)
        return llm

    async def delete(self, llm: LLM) -> None:
        llm_id = llm.id
        await self.db.delete(llm)
        await self.db.commit()
        await self.invalidate_cache(llm_id)

    async def get_context_by_id(
        self,
        llm_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> LLMContext | None:
        return await self.get_by_id_context(llm_id, use_cache=use_cache)

    @staticmethod
    def to_response(
        llm: LLM,
        *,
        can_edit: bool = False,
    ) -> LLMResponse:
        response = LLMResponse.model_validate(llm)
        response.can_edit = can_edit
        return response
