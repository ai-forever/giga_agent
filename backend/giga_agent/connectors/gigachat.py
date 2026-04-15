"""GigaChat connector runtime."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from gigachat.settings import AUTH_URL as GIGACHAT_DEFAULT_AUTH_URL
from gigachat.settings import BASE_URL as GIGACHAT_DEFAULT_BASE_URL
from langchain_gigachat import GigaChat
from pydantic import AliasChoices, Field

from giga_agent.conf import get_settings
from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.registry import ConnectorRegistry

# GigaChat SDK reads these env vars via pydantic BaseSettings.
# When explicit settings are provided, we must suppress env vars
# to prevent them from overriding the configured auth method.
_GIGACHAT_ENV_KEYS = (
    "GIGACHAT_CREDENTIALS",
    "GIGACHAT_ACCESS_TOKEN",
    "GIGACHAT_USER",
    "GIGACHAT_PASSWORD",
    "GIGACHAT_BASE_URL",
    "GIGACHAT_AUTH_URL",
    "GIGACHAT_SCOPE",
    "GIGACHAT_CERT_FILE",
    "GIGACHAT_KEY_FILE",
    "GIGACHAT_KEY_FILE_PASSWORD",
)


@contextmanager
def _suppress_gigachat_env():
    """Temporarily remove GIGACHAT_* env vars so SDK doesn't pick them up."""
    saved = {}
    for key in _GIGACHAT_ENV_KEYS:
        val = os.environ.pop(key, None)
        if val is not None:
            saved[key] = val
    try:
        yield
    finally:
        os.environ.update(saved)


@ConnectorRegistry.register("gigachat")
class GigaChatConnector(BaseConnector):
    gigachat_api_type: str | None = Field(
        default="prod",
        validation_alias=AliasChoices("gigachat_api_type", "api_type"),
    )
    gigachat_scope: str | None = Field(
        default="GIGACHAT_API_PERS",
        validation_alias=AliasChoices("gigachat_scope", "scope"),
    )
    gigachat_credentials: str | None = Field(
        default=None,
        validation_alias=AliasChoices("gigachat_credentials", "credentials"),
    )
    gigachat_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("gigachat_username", "username"),
    )
    gigachat_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("gigachat_password", "password"),
    )
    gigachat_base_url: str | None = Field(
        default_factory=lambda: GIGACHAT_DEFAULT_BASE_URL,
        validation_alias=AliasChoices("gigachat_base_url", "base_url"),
    )
    gigachat_auth_url: str | None = Field(
        default_factory=lambda: GIGACHAT_DEFAULT_AUTH_URL,
        validation_alias=AliasChoices("gigachat_auth_url", "auth_url"),
    )

    def _is_from_env_mode(self) -> bool:
        return (
            get_settings().giga_agent_gigachat_from_env
            and not self.model_fields_set
        )

    @classmethod
    async def validate_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        if get_settings().giga_agent_gigachat_from_env and not (settings or {}):
            return {}

        raw_base_url = str(
            (settings or {}).get("gigachat_base_url")
            or (settings or {}).get("base_url")
            or ""
        ).strip()
        validated = await super().validate_settings(settings)
        api_type = str(validated.get("gigachat_api_type", "prod") or "prod").strip().lower()
        if api_type not in {"prod", "dev"}:
            raise ValueError("gigachat_api_type must be one of: prod, dev")
        validated["gigachat_api_type"] = api_type

        scope = str(validated.get("gigachat_scope", "GIGACHAT_API_PERS") or "GIGACHAT_API_PERS").strip()
        if scope:
            validated["gigachat_scope"] = scope

        for key in ("gigachat_base_url", "gigachat_auth_url"):
            url = str(validated.get(key, "") or "").strip().rstrip("/")
            if url:
                validated[key] = url
            else:
                validated.pop(key, None)

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

        if api_type == "dev" and not raw_base_url:
            raise ValueError("gigachat_base_url is required for gigachat_api_type=dev")

        return validated

    def get_connection_kwargs(self) -> dict[str, Any] | None:
        if self._is_from_env_mode():
            return {"verify_ssl_certs": False, "streaming": True}

        api_type = str(self.gigachat_api_type or "prod").strip().lower()

        if api_type == "prod":
            return {
                "base_url": self.gigachat_base_url or GIGACHAT_DEFAULT_BASE_URL,
                "auth_url": self.gigachat_auth_url or GIGACHAT_DEFAULT_AUTH_URL,
                "credentials": self.gigachat_credentials or None,
                "scope": self.gigachat_scope or "GIGACHAT_API_PERS",
                "verify_ssl_certs": False,
                "streaming": True
            }

        if api_type == "dev":
            base_url = str(self.gigachat_base_url or "").strip().rstrip("/")
            if not base_url:
                return None
            return {
                "base_url": base_url,
                "user": self.gigachat_username,
                "password": self.gigachat_password,
                "verify_ssl_certs": False,
                "streaming": True,
            }

        return None

    def get_api_object(self) -> Any:
        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'gigachat'")
        if self._is_from_env_mode():
            return GigaChat(model="GigaChat", **kwargs)
        with _suppress_gigachat_env():
            return GigaChat(model="GigaChat", **kwargs)

    async def check_connection(self) -> bool:
        if self._is_from_env_mode():
            llm = GigaChat(verify_ssl_certs=False)
            await llm.aget_models()
            return True

        kwargs = self.get_connection_kwargs()
        if kwargs is None:
            raise ValueError("Invalid connection settings for connector type 'gigachat'")

        with _suppress_gigachat_env():
            llm = GigaChat(**kwargs)
        await llm.aget_models()
        return True
