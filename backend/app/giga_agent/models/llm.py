import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import String, DateTime, Uuid, ForeignKey, select, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, joinedload
from sqlalchemy.sql import func
from langchain_gigachat import GigaChat
from langchain_openai import ChatOpenAI

from giga_agent.core.db import Base, JSON_VARIANT


# ============ Exceptions ============


class ModelFetchError(Exception):
    """Ошибка при получении списка моделей от провайдера"""

    def __init__(self, provider_type: str, detail: str):
        self.provider_type = provider_type
        self.detail = detail
        super().__init__(f"Error fetching models from {provider_type}: {detail}")


# ============ Enums ============


class LLMProviderType(str, Enum):
    OPENAI = "openai"
    GIGACHAT = "gigachat"


# ============ SQLAlchemy Models ============


class LLMProvider(Base):
    """Провайдер LLM (OpenAI, Anthropic, GigaChat и т.д.)"""

    __tablename__ = "core_llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    # Relationships
    llm_models: Mapped[list["LLM"]] = relationship(
        "LLM", back_populates="provider", cascade="all, delete-orphan"
    )


class LLM(Base):
    """Конкретная LLM модель с настройками"""

    __tablename__ = "core_llms"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_llm_providers.id"), nullable=False, index=True
    )
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

    # Relationships
    provider: Mapped["LLMProvider"] = relationship(
        "LLMProvider", back_populates="llm_models"
    )


# ============ Pydantic Schemas ============


class LLMProviderSettings(BaseModel):
    """Настройки провайдера"""

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    gigachat_api_type: Optional[str] = "prod"
    gigachat_scope: Optional[str] = "GIGACHAT_API_PERS"
    gigachat_credentials: Optional[str] = None
    gigachat_username: Optional[str] = None
    gigachat_password: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


class LLMProviderBase(BaseModel):
    type: str
    name: Optional[str] = None
    settings: LLMProviderSettings = Field(default_factory=LLMProviderSettings)
    is_active: bool = True


class LLMProviderCreate(LLMProviderBase):
    pass


class LLMProviderUpdate(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[LLMProviderSettings] = None
    is_active: Optional[bool] = None


class LLMProviderResponse(LLMProviderBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LLMSettings(BaseModel):
    """Настройки модели"""

    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    extra: Optional[dict[str, Any]] = None


class LLMBase(BaseModel):
    model_id: str
    name: Optional[str] = None
    settings: LLMSettings = Field(default_factory=LLMSettings)
    is_active: bool = True


class LLMCreate(LLMBase):
    provider_id: uuid.UUID


class LLMUpdate(BaseModel):
    model_id: Optional[str] = None
    name: Optional[str] = None
    settings: Optional[LLMSettings] = None
    is_active: Optional[bool] = None


class LLMResponse(LLMBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AvailableModel(BaseModel):
    """Доступная модель от провайдера"""

    id: str
    name: Optional[str] = None
    created: Optional[int] = None
    owned_by: Optional[str] = None


# ============ Repository ============


class LLMProviderRepository:
    """Repository для работы с LLM провайдерами"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, provider_id: uuid.UUID) -> LLMProvider | None:
        """Получить провайдера по ID"""
        result = await self.db.execute(
            select(LLMProvider).where(LLMProvider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[LLMProvider]:
        """Получить все провайдеры пользователя"""
        query = select(LLMProvider).where(LLMProvider.owner_id == owner_id)
        if only_active:
            query = query.where(LLMProvider.is_active == True)
        query = query.order_by(LLMProvider.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_owner_and_type(
        self,
        owner_id: uuid.UUID,
        provider_type: str,
    ) -> LLMProvider | None:
        """Получить провайдера по владельцу и типу"""
        result = await self.db.execute(
            select(LLMProvider)
            .where(LLMProvider.owner_id == owner_id)
            .where(LLMProvider.type == provider_type)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        owner_id: uuid.UUID,
        provider_type: str,
        name: Optional[str] = None,
        settings: Optional[dict] = None,
        is_active: bool = True,
    ) -> LLMProvider:
        """Создать нового провайдера"""
        provider = LLMProvider(
            owner_id=owner_id,
            type=provider_type,
            name=name,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(provider)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def update(
        self,
        provider: LLMProvider,
        **kwargs,
    ) -> LLMProvider:
        """Обновить провайдера"""
        for key, value in kwargs.items():
            if hasattr(provider, key) and value is not None:
                setattr(provider, key, value)
        await self.db.commit()
        await self.db.refresh(provider)
        return provider

    async def delete(self, provider: LLMProvider) -> None:
        """Удалить провайдера"""
        await self.db.delete(provider)
        await self.db.commit()

    @staticmethod
    def to_response(provider: LLMProvider) -> LLMProviderResponse:
        """Преобразовать в Pydantic response"""
        return LLMProviderResponse.model_validate(provider)

    # ============ API Helpers ============

    @staticmethod
    def get_connection_kwargs(provider_type: str, settings: dict) -> dict | None:
        """
        Получить параметры подключения для провайдера.

        Returns:
            dict с параметрами подключения или None, если параметры невалидны.
        """
        if provider_type in (LLMProviderType.OPENAI, "openai"):
            api_key = settings.get("api_key", "")
            base_url = settings.get("base_url")
            return {
                "api_key": api_key,
                "base_url": base_url.rstrip("/") if base_url else None,
            }
        elif provider_type in (LLMProviderType.GIGACHAT, "gigachat"):
            api_type = settings.get("gigachat_api_type") or "prod"
            if api_type in ("prod", "preview"):
                base_url = (
                    None
                    if api_type == "prod"
                    else LLMProviderRepository.PREVIEW_URL
                )
                return {
                    "base_url": base_url,
                    "credentials": settings.get("gigachat_credentials") or None,
                    "scope": settings.get("gigachat_scope") or "GIGACHAT_API_PERS",
                    "verify_ssl_certs": False,
                }
            else:
                # dev
                base_url = (settings.get("base_url") or "").strip()
                if not base_url:
                    return None
                return {
                    "base_url": base_url.rstrip("/"),
                    "user": settings.get("gigachat_username"),
                    "password": settings.get("gigachat_password"),
                }
        return None

    @staticmethod
    async def fetch_available_models(provider: LLMProvider) -> list[AvailableModel]:
        """
        Получить список доступных моделей от провайдера.
        Поддерживает OpenAI-совместимый API.
        """
        provider_type = provider.type
        settings = provider.settings or {}
        if provider_type == LLMProviderType.OPENAI or provider_type == "openai":
            return await LLMProviderRepository._fetch_openai_models(settings)
        elif provider_type == LLMProviderType.GIGACHAT or provider_type == "gigachat":
            return await LLMProviderRepository._fetch_gigachat_models(settings)

        return []

    @staticmethod
    async def _fetch_openai_models(settings: dict) -> list[AvailableModel]:
        """Получить модели через OpenAI API"""
        kwargs = LLMProviderRepository.get_connection_kwargs("openai", settings)
        if not kwargs or not kwargs.get("api_key"):
            return []

        try:
            client = AsyncOpenAI(
                **kwargs,
                timeout=30.0,
            )

            response = await client.models.list()

            models = []
            for model in response.data:
                models.append(
                    AvailableModel(
                        id=model.id,
                        name=model.id,
                        created=model.created,
                        owned_by=model.owned_by,
                    )
                )

            # Сортируем по имени
            models.sort(key=lambda m: m.id)
            return models

        except Exception as e:
            raise ModelFetchError("openai", str(e)) from e

    PREVIEW_URL = "https://gigachat.devices.sberbank.ru/api/v1"

    @staticmethod
    async def _fetch_gigachat_models(settings: dict) -> list[AvailableModel]:
        """
        Получить список моделей GigaChat в зависимости от типа API:
        prod — базовый URL по умолчанию в библиотеке, credentials;
        preview — PREVIEW_URL + credentials;
        dev — base_url + user + password.
        """
        kwargs = LLMProviderRepository.get_connection_kwargs("gigachat", settings)
        if kwargs is None:
            return []

        try:
            llm = GigaChat(**kwargs)
            return [
                AvailableModel(id=model.id_, name=model.id_, owned_by=model.owned_by)
                for model in (await llm.aget_models()).data
            ]
        except Exception as e:
            raise ModelFetchError("gigachat", str(e)) from e


class LLMRepository:
    """Repository для работы с LLM моделями"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, llm_id: uuid.UUID) -> LLM | None:
        """Получить модель по ID"""
        result = await self.db.execute(select(LLM).where(LLM.id == llm_id))
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[LLM]:
        """Получить все модели пользователя"""
        query = select(LLM).where(LLM.owner_id == owner_id)
        if only_active:
            query = query.where(LLM.is_active == True)
        query = query.order_by(LLM.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_provider(
        self,
        provider_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[LLM]:
        """Получить все модели провайдера"""
        query = select(LLM).where(LLM.provider_id == provider_id)
        if only_active:
            query = query.where(LLM.is_active == True)
        query = query.order_by(LLM.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_model_id(
        self,
        owner_id: uuid.UUID,
        model_id: str,
    ) -> LLM | None:
        """Получить модель по model_id и владельцу"""
        result = await self.db.execute(
            select(LLM).where(LLM.owner_id == owner_id).where(LLM.model_id == model_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID,
        model_id: str,
        name: Optional[str] = None,
        settings: Optional[dict] = None,
        is_active: bool = True,
    ) -> LLM:
        """Создать новую модель"""
        llm = LLM(
            owner_id=owner_id,
            provider_id=provider_id,
            model_id=model_id,
            name=name,
            settings=settings or {},
            is_active=is_active,
        )
        self.db.add(llm)
        await self.db.commit()
        await self.db.refresh(llm)
        return llm

    async def update(
        self,
        llm: LLM,
        **kwargs,
    ) -> LLM:
        """Обновить модель"""
        for key, value in kwargs.items():
            if hasattr(llm, key) and value is not None:
                setattr(llm, key, value)
        await self.db.commit()
        await self.db.refresh(llm)
        return llm

    async def delete(self, llm: LLM) -> None:
        """Удалить модель"""
        await self.db.delete(llm)
        await self.db.commit()

    async def exists_by_model_id(
        self,
        owner_id: uuid.UUID,
        model_id: str,
    ) -> bool:
        """Проверить существует ли модель с таким model_id у пользователя"""
        llm = await self.get_by_model_id(owner_id, model_id)
        return llm is not None

    async def get_langchain_chat_by_id(
        self, llm_id: uuid.UUID
    ) -> GigaChat | ChatOpenAI:
        """
        Получить LangChain chat model по ID.

        Загружает LLM и его провайдер одним запросом (JOIN),
        формирует connection kwargs и создаёт GigaChat или ChatOpenAI.
        """
        result = await self.db.execute(
            select(LLM)
            .where(LLM.id == llm_id)
            .options(joinedload(LLM.provider))
        )
        llm = result.scalar_one_or_none()
        if llm is None:
            raise ValueError(f"LLM with id {llm_id} not found")

        provider = llm.provider
        settings = provider.settings or {}
        kwargs = LLMProviderRepository.get_connection_kwargs(provider.type, settings)
        if kwargs is None:
            raise ValueError(
                f"Invalid connection settings for provider {provider.id}"
            )

        if provider.type in (LLMProviderType.OPENAI, "openai"):
            return ChatOpenAI(model=llm.model_id, **kwargs)
        elif provider.type in (LLMProviderType.GIGACHAT, "gigachat"):
            return GigaChat(model=llm.model_id, **kwargs)
        else:
            raise ValueError(f"Unsupported provider type: {provider.type}")

    @staticmethod
    def to_response(llm: LLM) -> LLMResponse:
        """Преобразовать в Pydantic response"""
        return LLMResponse.model_validate(llm)
