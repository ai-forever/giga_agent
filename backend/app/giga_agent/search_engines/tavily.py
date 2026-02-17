"""Search engine via Tavily Search API."""

from __future__ import annotations

import os
from typing import Any

from langchain_tavily import TavilySearch
from pydantic import Field, PrivateAttr

from giga_agent.search_engines.base import BaseSearchEngine
from giga_agent.search_engines.registry import SearchEngineRegistry


@SearchEngineRegistry.register("tavily")
class TavilySearchEngine(BaseSearchEngine):
    """Tavily search engine runtime."""

    api_key: str | None = Field(default=None, description="Tavily API key")

    _api_key: str | None = PrivateAttr(default=None)
    _search_tool: TavilySearch | None = PrivateAttr(default=None)

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["tavily"]

    @classmethod
    def connector_settings_fields(cls) -> set[str]:
        return {"api_key"}

    async def init(self) -> None:
        resolved_api_key = self._resolve_api_key()
        if not resolved_api_key:
            raise ValueError(
                "Tavily API key is not configured. "
                "Provide connector credentials or set TAVILY_API_KEY."
            )

        self._api_key = resolved_api_key
        self._search_tool = TavilySearch(tavily_api_key=resolved_api_key)
        await super().init()

    async def _search(self, queries: list[str]) -> list[dict[str, Any]]:
        if self._search_tool is None:
            raise RuntimeError("TavilySearchEngine is not initialized. Call init().")

        prepared_queries = [query.strip() for query in queries if query.strip()]
        if not prepared_queries:
            return []

        results = await self._search_tool.abatch(
            [{"query": query} for query in prepared_queries]
        )
        return [
            {"query": query, "result": result}
            for query, result in zip(prepared_queries, results)
        ]

    def _resolve_api_key(self) -> str:
        from_settings = (self.api_key or "").strip()
        if from_settings:
            return from_settings
        return (os.getenv("TAVILY_API_KEY") or "").strip()
