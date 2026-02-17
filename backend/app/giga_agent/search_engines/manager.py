"""Manager для резолва runtime search engine текущего пользователя."""

from __future__ import annotations

import uuid

from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import UserShort
from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.search_engines.registry import SearchEngineRegistry


class SearchEngineManager:
    @staticmethod
    async def resolve_for_user(
        owner_id: uuid.UUID,
        user: UserShort,
    ) -> BaseSearchEngine:
        engine_id = user.search_engine_id
        if engine_id is None:
            raise ValueError(
                "У пользователя не выбран поисковый движок. "
                "Установите search_engine_id в настройках пользователя."
            )

        record = await SearchEngineRepository.get_cached_or_db(
            engine_id,
            use_cache=True,
        )
        if record is None:
            raise ValueError(f"Поисковый движок {engine_id} не найден.")
        if record.owner_id != owner_id:
            raise ValueError(
                f"Поисковый движок {engine_id} не принадлежит пользователю {owner_id}."
            )
        if not record.is_active:
            raise ValueError(
                f"Поисковый движок {engine_id} неактивен."
            )

        runtime_cls = SearchEngineRegistry.get(record.type)
        engine = runtime_cls(**(record.settings or {}))
        await engine.init()
        return engine
