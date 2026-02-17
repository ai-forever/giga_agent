"""Manager for resolving runtime search engines."""

from __future__ import annotations

import uuid

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.search_engines.registry import SearchEngineRegistry


class SearchEngineManager:
    @staticmethod
    async def resolve_by_id(engine_id: uuid.UUID) -> BaseSearchEngine:
        record = await SearchEngineRepository.get_cached_or_db(engine_id, use_cache=True)
        if record is None:
            raise ValueError(f"Поисковый движок {engine_id} не найден.")
        if not record.is_active:
            raise ValueError(f"Поисковый движок {engine_id} неактивен.")

        runtime_cls = SearchEngineRegistry.get(record.type)

        supported_connector_types = {
            item.lower() for item in runtime_cls.supported_connector_types()
        }
        connector_kwargs: dict = {}

        if supported_connector_types:
            connector_id = record.connector_id
            if connector_id is None:
                raise ValueError(
                    f"Поисковый движок {engine_id} требует connector. "
                    f"Supported connector types: {sorted(supported_connector_types)}"
                )

            connector = await ConnectorRepository.get_cached_or_db(
                connector_id,
                use_cache=True,
            )
            if connector is None:
                raise ValueError(f"Connector {connector_id} не найден.")
            if not connector.is_active:
                raise ValueError(f"Connector {connector_id} неактивен.")

            connector_type = (connector.type or "").lower()
            if connector_type not in supported_connector_types:
                raise ValueError(
                    f"Connector type '{connector_type}' не поддерживается search engine '{record.type}'. "
                    f"Supported: {sorted(supported_connector_types)}"
                )

            connector_kwargs = ConnectorRegistry.get_connection_kwargs(
                connector.type,
                connector.settings or {},
            )
            if connector_kwargs is None:
                raise ValueError(f"Некорректные настройки connector {connector_id}.")

        engine = runtime_cls(**(record.settings or {}), **connector_kwargs)
        await engine.init()
        return engine
