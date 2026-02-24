"""Tavily connector runtime."""

from __future__ import annotations

import os
from typing import Any

from pydantic import Field

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry


@ConnectorRegistry.register("tavily")
class TavilyConnector(BaseConnector):
    api_key: str | None = Field(default=None, description="Tavily API key")

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        validated = await super().validate_settings(settings)

        provided = str(validated.get("api_key", "") or "").strip()
        from_env = (os.getenv("TAVILY_API_KEY") or "").strip()

        if provided:
            validated["api_key"] = provided
            return validated

        if from_env:
            validated.pop("api_key", None)
            return validated

        raise ValueError(
            "Tavily api_key is required when TAVILY_API_KEY environment variable is not set."
        )

    def get_connection_kwargs(self) -> dict[str, Any] | None:
        api_key = str(self.api_key or "").strip() or (
            os.getenv("TAVILY_API_KEY") or ""
        ).strip()
        if not api_key:
            return None
        return {"api_key": api_key}

    def get_api_object(self) -> Any:
        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'tavily'")
        return kwargs
