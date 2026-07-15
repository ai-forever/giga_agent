"""OpenAI-compatible connector runtime."""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import Field

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


@ConnectorRegistry.register("openai")
class OpenAIConnector(BaseConnector):
    base_url: str | None = Field(default=None, description="OpenAI API base URL")
    api_key: str | None = Field(default=None, description="OpenAI API key")

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        validated = await super().validate_settings(settings)

        api_key = str(validated.get("api_key", "") or "").strip()
        env_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key and not env_api_key:
            raise ValueError(
                "OpenAI api_key is required when OPENAI_API_KEY environment variable is not set."
            )

        if api_key:
            validated["api_key"] = api_key
        else:
            validated.pop("api_key", None)

        base_url = str(validated.get("base_url", "") or "").strip().rstrip("/")
        validated["base_url"] = base_url or OPENAI_DEFAULT_BASE_URL

        return validated

    def get_connection_kwargs(self) -> dict[str, Any] | None:
        api_key = (
            str(self.api_key or "").strip()
            or (os.getenv("OPENAI_API_KEY") or "").strip()
        )
        base_url = str(self.base_url or "").strip().rstrip("/")

        if not api_key:
            return None

        return {
            "api_key": api_key,
            "base_url": base_url or OPENAI_DEFAULT_BASE_URL,
        }

    def get_api_object(self) -> Any:
        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'openai'")
        return ChatOpenAI(model="gpt-4o-mini", **kwargs)

    async def check_connection(self) -> bool:
        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'openai'")

        client = AsyncOpenAI(**kwargs, timeout=30.0)
        await client.models.list()
        return True
