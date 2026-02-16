import uuid
from datetime import datetime
from typing import Optional, Any

from cashews import cache
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT, get_session_factory


# ============ SQLAlchemy Models ============


class ImageGenerator(Base):
    """Генератор изображений, привязанный к пользователю."""

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
    llm_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "core_llm_providers.id",
            name="fk_core_image_generators_llm_provider_id",
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


# ============ Pydantic Schemas ============


class ImageGeneratorBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    llm_provider_id: Optional[uuid.UUID] = None
    is_active: bool = True


class ImageGeneratorCreate(ImageGeneratorBase):
    pass


class ImageGeneratorUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    llm_provider_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class ImageGeneratorResponse(ImageGeneratorBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Repository ============


class ImageGeneratorRepository:
    """Repository для работы с генераторами изображений."""

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
        session: AsyncSession | None = None,
        use_cache: bool = True,
    ) -> ImageGeneratorResponse | None:
        if use_cache:
            cached = await cls.get_from_cache(generator_id)
            if cached is not None:
                return cached

        if session is not None:
            return await cls(session).get_by_id_response(generator_id, use_cache=False)

        factory = await get_session_factory()
        async with factory() as db:
            return await cls(db).get_by_id_response(generator_id, use_cache=False)

    @staticmethod
    async def invalidate_cache(generator_id: uuid.UUID) -> None:
        await cache.delete(ImageGeneratorRepository.cache_key(generator_id))

    async def get_by_id(self, generator_id: uuid.UUID) -> ImageGenerator | None:
        """Получить генератор по ID."""
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
        """Получить все генераторы пользователя."""
        query = select(ImageGenerator).where(ImageGenerator.owner_id == owner_id)
        if only_active:
            query = query.where(ImageGenerator.is_active == True)  # noqa: E712
        query = query.order_by(ImageGenerator.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_owner_and_type(
        self,
        owner_id: uuid.UUID,
        generator_type: str,
    ) -> ImageGenerator | None:
        """Получить генератор по владельцу и типу."""
        result = await self.db.execute(
            select(ImageGenerator)
            .where(ImageGenerator.owner_id == owner_id)
            .where(ImageGenerator.type == generator_type)
        )
        return result.scalar_one_or_none()

    async def get_by_llm_provider(
        self,
        llm_provider_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[ImageGenerator]:
        """Получить генераторы, привязанные к LLM провайдеру."""
        query = select(ImageGenerator).where(
            ImageGenerator.llm_provider_id == llm_provider_id
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
        llm_provider_id: Optional[uuid.UUID] = None,
        is_active: bool = True,
    ) -> ImageGenerator:
        """Создать новый генератор."""
        generator = ImageGenerator(
            owner_id=owner_id,
            type=generator_type,
            name=name,
            settings=settings or {},
            llm_provider_id=llm_provider_id,
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
        """Обновить генератор."""
        for key, value in kwargs.items():
            if hasattr(generator, key) and value is not None:
                setattr(generator, key, value)
        await self.db.commit()
        await self.db.refresh(generator)
        await self.invalidate_cache(generator.id)
        return generator

    async def delete(self, generator: ImageGenerator) -> None:
        """Удалить генератор."""
        generator_id = generator.id
        await self.db.delete(generator)
        await self.db.commit()
        await self.invalidate_cache(generator_id)

    @staticmethod
    def to_response(generator: ImageGenerator) -> ImageGeneratorResponse:
        """Преобразовать в Pydantic response."""
        return ImageGeneratorResponse.model_validate(generator)
