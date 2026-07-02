"""Provider abstraction for OAuth / token integrations.

An :class:`IntegrationProvider` is the "service model": it knows how a user
connects to a given service (an OAuth authorization link and/or a manually
entered token), can produce a fresh access token at call time (refreshing
transparently), and can report whether the connection is healthy or needs
re-authorization.

Concrete implementations:
- :class:`~giga_agent.core.integrations.static_provider.StaticOAuthProvider`
  — fixed endpoints + client creds from config (Yandex, Google, ...), and
  manual-token providers (GitHub PAT).
- :class:`~giga_agent.core.integrations.mcp_provider.McpServerProvider`
  — dynamic discovery + DCR, wrapping an :class:`McpServer` row.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

AuthKind = Literal["oauth2", "manual_token", "both"]
ConnStatus = Literal["not_connected", "connected", "needs_reauth"]


@dataclass
class ManualField:
    """A field the user fills when entering a token manually."""

    key: str
    label: str
    secret: bool = True
    placeholder: str | None = None


@dataclass
class ConnectionStatus:
    status: ConnStatus
    detail: str | None = None
    scope: str | None = None
    token_hint: str | None = None


@dataclass
class ProviderInfo:
    """Public (no-secrets) description of a provider for the API/UI."""

    key: str
    label: str
    icon: str | None
    auth_kind: AuthKind
    manual_fields: list[ManualField] = field(default_factory=list)


class IntegrationProvider(ABC):
    key: str
    label: str
    icon: str | None = None
    auth_kind: AuthKind = "oauth2"
    manual_fields: list[ManualField] = []

    # -- connect -------------------------------------------------------------- #

    async def authorization_url(
        self, *, user_id: uuid.UUID, db, base_url: str
    ) -> str:
        """Build the provider authorization URL (OAuth providers only)."""
        raise NotImplementedError(
            f"provider '{self.key}' does not support OAuth authorization"
        )

    async def store_manual_token(
        self, *, user_id: uuid.UUID, fields: dict[str, str]
    ) -> None:
        """Persist a manually-entered token (manual_token providers only)."""
        raise NotImplementedError(
            f"provider '{self.key}' does not support manual tokens"
        )

    # -- use ------------------------------------------------------------------ #

    @abstractmethod
    async def access_token(self, *, user_id: uuid.UUID) -> str:
        """Return a fresh access token, refreshing if needed.

        Raises :class:`ReauthRequired` when no usable token can be produced.
        """

    @abstractmethod
    async def status(self, *, user_id: uuid.UUID) -> ConnectionStatus: ...

    async def disconnect(self, *, user_id: uuid.UUID) -> None:
        """Remove stored credentials for this user."""
        from giga_agent.core.db import get_session_factory
        from giga_agent.models.oauth_connection import OAuthConnectionRepository

        factory = await get_session_factory()
        async with factory() as session:
            await OAuthConnectionRepository(session).delete(user_id, self.key)

    async def validate(self, token: str) -> bool:
        """Optional liveness probe. Default: assume valid."""
        _ = token
        return True

    # -- helpers -------------------------------------------------------------- #

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            key=self.key,
            label=self.label,
            icon=self.icon,
            auth_kind=self.auth_kind,
            manual_fields=list(self.manual_fields),
        )

    @property
    def supports_oauth(self) -> bool:
        return self.auth_kind in ("oauth2", "both")

    @property
    def supports_manual(self) -> bool:
        return self.auth_kind in ("manual_token", "both")
