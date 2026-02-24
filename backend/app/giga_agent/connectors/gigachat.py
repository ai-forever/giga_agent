"""GigaChat connector runtime."""

from __future__ import annotations

from typing import Any

from langchain_gigachat import GigaChat
from pydantic import Field

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry


PREVIEW_URL = "https://gigachat.devices.sberbank.ru/api/v1"


@ConnectorRegistry.register("gigachat")
class GigaChatConnector(BaseConnector):
    base_url: str | None = Field(default=None)
    gigachat_api_type: str | None = Field(default="prod")
    gigachat_scope: str | None = Field(default="GIGACHAT_API_PERS")
    gigachat_credentials: str | None = Field(default=None)
    gigachat_username: str | None = Field(default=None)
    gigachat_password: str | None = Field(default=None)

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        validated = await super().validate_settings(settings)
        api_type = str(validated.get("gigachat_api_type", "prod") or "prod").strip().lower()
        if api_type not in {"prod", "preview", "dev"}:
            raise ValueError("gigachat_api_type must be one of: prod, preview, dev")
        validated["gigachat_api_type"] = api_type

        scope = str(validated.get("gigachat_scope", "GIGACHAT_API_PERS") or "GIGACHAT_API_PERS").strip()
        if scope:
            validated["gigachat_scope"] = scope

        base_url = str(validated.get("base_url", "") or "").strip().rstrip("/")
        if base_url:
            validated["base_url"] = base_url
        else:
            validated.pop("base_url", None)

        for key in (
            "gigachat_credentials",
            "gigachat_username",
            "gigachat_password",
        ):
            val = str(validated.get(key, "") or "").strip()
            if val:
                validated[key] = val
            else:
                validated.pop(key, None)

        if api_type == "dev" and not validated.get("base_url"):
            raise ValueError("base_url is required for gigachat_api_type=dev")

        return validated

    def get_connection_kwargs(self) -> dict[str, Any] | None:
        api_type = str(self.gigachat_api_type or "prod").strip().lower()

        if api_type in {"prod", "preview"}:
            return {
                "base_url": None if api_type == "prod" else PREVIEW_URL,
                "credentials": self.gigachat_credentials or None,
                "scope": self.gigachat_scope or "GIGACHAT_API_PERS",
                "verify_ssl_certs": False,
            }

        if api_type == "dev":
            base_url = str(self.base_url or "").strip().rstrip("/")
            if not base_url:
                return None
            return {
                "base_url": base_url,
                "user": self.gigachat_username,
                "password": self.gigachat_password,
            }

        return None

    def get_api_object(self) -> Any:
        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'gigachat'")
        return GigaChat(model="GigaChat", **kwargs)
