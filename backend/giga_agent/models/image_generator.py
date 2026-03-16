import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)


class ImageGenerator(Base):
    """Image generator configuration bound to a connector (optional)."""

    __tablename__ = "core_image_generators"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_image_generators_owner_id"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_connectors.id",
            name="fk_core_image_generators_connector_id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class ImageGeneratorBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    connector_id: Optional[uuid.UUID] = None
    is_active: bool = True


class ImageGeneratorCreate(ImageGeneratorBase):
    check_connection: bool = True
    permissions: ResourcePermissionsPayload | None = None


class ImageGeneratorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    connector_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class ImageGeneratorResponse(ImageGeneratorBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ImageGeneratorRepository(ACLResourceRepositoryMixin[ImageGenerator]):
    """Repository for image generators."""
    resource_model = ImageGenerator
    resource_type = "image_generator"

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(generator_id: uuid.UUID) -> str:
        return f"image_generator:ctx:{generator_id}"

    @staticmethod
    async def get_from_cache(
        generator_id: uuid.UUID,
    ) -> ImageGeneratorResponse | None:
        cached = await cache.get(ImageGeneratorRepository.cache_key(generator_id))
        if cached is None:
            return None
        return ImageGeneratorResponse.model_validate(cached)

    @classmethod
    async def get_cached_or_db(
        cls,
        generator_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> ImageGeneratorResponse | None:
        cached = await cls.get_from_cache(generator_id)
        if cached is not None:
            return cached

        return await cls(session).get_by_id_response(generator_id, use_cache=False)

    @staticmethod
    async def invalidate_cache(generator_id: uuid.UUID) -> None:
        await cache.delete(ImageGeneratorRepository.cache_key(generator_id))

    async def get_by_id(self, generator_id: uuid.UUID) -> ImageGenerator | None:
        result = await self.db.execute(
            select(ImageGenerator).where(ImageGenerator.id == generator_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_response(
        self,
        generator_id: uuid.UUID,
        *,
        use_cache: bool = True,
    ) -> ImageGeneratorResponse | None:
        if use_cache:
            cached = await self.get_from_cache(generator_id)
            if cached is not None:
                return cached

        generator = await self.get_by_id(generator_id)
        if generator is None:
            return None

        response = self.to_response(generator)
        await cache.set(
            self.cache_key(generator_id),
            response.model_dump(mode="json"),
            expire="5m",
        )
        return response

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[ImageGenerator]:
        query = select(ImageGenerator).where(ImageGenerator.owner_id == owner_id)
        if only_active:
            query = query.where(ImageGenerator.is_active == True)  # noqa: E712
        query = query.order_by(ImageGenerator.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[ImageGenerator]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_with_access_for_user(
        self,
        generator_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[ImageGenerator, bool, bool] | None:
        return await super().get_by_id_with_access_for_user(
            generator_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

    async def get_by_id_readable(
        self,
        generator_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> ImageGenerator | None:
        row = await self.get_by_id_with_access_for_user(
            generator_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        generator, can_read, _ = row
        if not can_read:
            return None
        return generator

    async def get_by_id_writable(
        self,
        generator_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> ImageGenerator | None:
        row = await self.get_by_id_with_access_for_user(
            generator_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        if row is None:
            return None
        generator, _, can_edit = row
        if not can_edit:
            return None
        return generator

    async def get_writable_ids_for_user(
        self,
        *,
        user_id: uuid.UUID,
        resource_ids: list[uuid.UUID],
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        return await ResourcePermissionRepository(self.db).list_resource_ids_with_access(
            user_id=user_id,
            resource_type="image_generator",
            resource_ids=resource_ids,
            permission="write",
            user_group_ids=user_group_ids,
        )

    async def get_by_owner_and_type(
        self,
        owner_id: uuid.UUID,
        generator_type: str,
    ) -> ImageGenerator | None:
        result = await self.db.execute(
            select(ImageGenerator)
            .where(ImageGenerator.owner_id == owner_id)
            .where(ImageGenerator.type == generator_type)
        )
        return result.scalar_one_or_none()

    async def get_by_connector(
        self,
        connector_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[ImageGenerator]:
        query = select(ImageGenerator).where(
            ImageGenerator.connector_id == connector_id
        )
        if only_active:
            query = query.where(ImageGenerator.is_active == True)  # noqa: E712
        query = query.order_by(ImageGenerator.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        owner_id: uuid.UUID,
        generator_type: str,
        name: Optional[str] = None,
        settings: Optional[dict] = None,
        connector_id: Optional[uuid.UUID] = None,
        is_active: bool = True,
    ) -> ImageGenerator:
        generator = ImageGenerator(
            owner_id=owner_id,
            type=generator_type,
            name=name,
            settings=settings or {},
            connector_id=connector_id,
            is_active=is_active,
        )
        self.db.add(generator)
        await self.db.commit()
        await self.db.refresh(generator)
        await cache.set(
            self.cache_key(generator.id),
            self.to_response(generator).model_dump(mode="json"),
            expire="5m",
        )
        return generator

    async def update(
        self,
        generator: ImageGenerator,
        **kwargs: Any,
    ) -> ImageGenerator:
        for key, value in kwargs.items():
            if hasattr(generator, key):
                setattr(generator, key, value)
        await self.db.commit()
        await self.db.refresh(generator)
        await self.invalidate_cache(generator.id)
        return generator

    async def delete(self, generator: ImageGenerator) -> None:
        generator_id = generator.id
        await ResourcePermissionRepository(self.db).revoke_all_for_resource(
            resource_type="image_generator",
            resource_id=generator_id,
            no_commit=True,
        )
        await self.db.delete(generator)
        await self.db.commit()
        await self.invalidate_cache(generator_id)

    @staticmethod
    def to_response(
        generator: ImageGenerator,
        *,
        can_edit: bool = False,
    ) -> ImageGeneratorResponse:
        response = ImageGeneratorResponse.model_validate(generator)
        response.can_edit = can_edit
        return response
