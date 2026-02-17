"""LangChain tool для выполнения веб-поиска через выбранный search engine."""

from __future__ import annotations

import uuid
from typing import Any, Annotated

from langchain.tools import ToolRuntime, tool
from pydantic import Field

from giga_agent.models.users import UserRepository
from giga_agent.search_engines.manager import SearchEngineManager

# Убедимся, что провайдеры зарегистрированы
import giga_agent.search_engines  # noqa: F401


@tool
async def search(
    queries: Annotated[list[str], Field(description="Список поисковых запросов")],
    runtime: ToolRuntime,
) -> list[dict[str, Any]]:
    """Выполняет поиск по списку запросов через текущий поисковый движок пользователя."""
    if runtime is None:
        raise ValueError("Tool runtime is required.")

    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    user = await UserRepository.get_cached_or_db(owner_id)
    if user is None:
        raise ValueError(f"Пользователь {owner_id} не найден")

    engine = await SearchEngineManager.resolve_for_user(owner_id, user)
    return await engine.search(queries)
