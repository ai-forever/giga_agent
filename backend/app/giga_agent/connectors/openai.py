"""OpenAI-compatible connector runtime."""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import Field

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry


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
        if base_url:
            validated["base_url"] = base_url
        else:
            validated.pop("base_url", None)

        return validated

    @classmethod
    def get_connection_kwargs(cls, settings: dict[str, Any]) -> dict[str, Any] | None:
        api_key = str(settings.get("api_key", "") or "").strip() or (
            os.getenv("OPENAI_API_KEY") or ""
        ).strip()
        base_url = str(settings.get("base_url", "") or "").strip().rstrip("/")

        if not api_key:
            return None

        return {
            "api_key": api_key,
            "base_url": base_url or None,
        }

    @classmethod
    def get_api_object(cls, settings: dict[str, Any]) -> Any:
        kwargs = cls.get_connection_kwargs(settings)
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'openai'")
        return ChatOpenAI(model="gpt-4o-mini", **kwargs)
