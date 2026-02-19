"""Manager for resolving runtime image generators."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.generators.image.base import BaseImageGenerator
from giga_agent.generators.image.registry import ImageGeneratorRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.image_generator import ImageGeneratorRepository

# Ensure providers are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.generators.image  # noqa: F401


class ImageGeneratorManager:
    @staticmethod
    async def resolve_by_id(
        generator_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> BaseImageGenerator:
        record = await ImageGeneratorRepository.get_cached_or_db(
            generator_id,
            session=session,
        )
        if record is None:
            raise ValueError(f"Генератор изображений {generator_id} не найден.")
        if not record.is_active:
            raise ValueError(f"Генератор изображений {generator_id} неактивен.")

        runtime_cls = ImageGeneratorRegistry.get(record.type)
        supported_types = [item.lower() for item in runtime_cls.supported_connector_types()]

        llm = None
        if supported_types:
            connector_id = record.connector_id
            if connector_id is None:
                raise ValueError(
                    f"Image generator '{record.type}' requires connector. "
                    f"Supported connector types: {supported_types}"
                )

            connector = await ConnectorRepository.get_cached_or_db(
                connector_id,
                session=session,
            )
            if connector is None:
                raise ValueError(f"Connector {connector_id} not found")
            if not connector.is_active:
                raise ValueError(f"Connector {connector.id} is inactive.")

            connector_type = (connector.type or "").lower()
            if connector_type not in supported_types:
                raise ValueError(
                    f"Connector type '{connector_type}' is not supported by "
                    f"image generator '{record.type}'. Supported types: {supported_types}"
                )

            llm = ConnectorRegistry.get_api_object(
                connector_type,
                connector.settings or {},
            )
        elif record.connector_id is not None:
            raise ValueError(
                f"Image generator '{record.type}' does not support connectors."
            )

        generator = runtime_cls(
            **(record.settings or {}),
            llm=llm,
        )
        await generator.init()
        return generator
