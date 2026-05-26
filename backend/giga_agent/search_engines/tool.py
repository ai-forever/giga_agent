"""LangChain tool для выполнения веб-поиска через выбранный search engine."""

from __future__ import annotations

from typing import Any, Annotated

from langchain.tools import ToolRuntime, tool
from pydantic import Field

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

    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    resolver = RuntimeResolver.from_config(runtime.config)
    if not resolver.has_search_engine:
        raise ValueError(
            "У пользователя не выбран поисковый движок. "
            "Настройте search_engine в runtime."
        )
    engine = await resolver.get_search_engine()
    return await engine.search(queries)
