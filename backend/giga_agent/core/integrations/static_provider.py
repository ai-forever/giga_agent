"""Static-config OAuth providers (Yandex, Google, ...) and manual-token providers.

Unlike MCP servers (dynamic discovery + DCR), these have fixed authorization /
token endpoints and a single app-wide client_id/secret supplied via config.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from mcp.client.auth import PKCEParameters

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.oauth_connection import OAuthConnectionRepository
from giga_agent.core.integrations import oauth_flow, state
from giga_agent.core.integrations.base import (
    AuthKind,
    ConnectionStatus,
    IntegrationProvider,
    ManualField,
)
from giga_agent.core.integrations.errors import ReauthRequired
from giga_agent.core.integrations.token_storage import integrations_callback_url

logger = get_logger(__name__)

# Treat a token expiring within this window as already stale, so we refresh
# before handing it to a caller rather than mid-request.
_EXPIRY_LEEWAY_SECONDS = 60


@dataclass
class StaticOAuthConfig:
    key: str
    label: str
    icon: str | None = None
    auth_kind: AuthKind = "oauth2"
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    extra_auth_params: dict[str, str] = field(default_factory=dict)
    # Optional liveness probe: GET with Bearer token; 2xx → valid.
    validate_url: str | None = None
    manual_fields: list[ManualField] = field(default_factory=list)
    # Some APIs (Yandex) use ``Authorization: OAuth <token>`` rather than Bearer.
    auth_header_scheme: str = "Bearer"


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"****{value[-4:]}" if len(value) > 4 else "****"


class StaticOAuthProvider(IntegrationProvider):
    def __init__(self, config: StaticOAuthConfig) -> None:
        self._cfg = config
        self.key = config.key
        self.label = config.label
        self.icon = config.icon
        self.auth_kind = config.auth_kind
        self.manual_fields = list(config.manual_fields)

    # -- connect -------------------------------------------------------------- #

    async def authorization_url(self, *, user_id: uuid.UUID, db, base_url: str) -> str:
        cfg = self._cfg
        if not (cfg.authorization_endpoint and cfg.token_endpoint and cfg.client_id):
            raise ValueError(f"provider '{self.key}' is not configured for OAuth")
        redirect_uri = integrations_callback_url(base_url)
        pkce = PKCEParameters.generate()
        st = secrets.token_urlsafe(32)
        await state.store_oauth_state(
            namespace=state.INTEGRATIONS_STATE_NS,
            state=st,
            data={
                "user_id": str(user_id),
                "provider_key": self.key,
                "code_verifier": pkce.code_verifier,
                "token_endpoint": cfg.token_endpoint,
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "redirect_uri": redirect_uri,
                "scope": cfg.scope,
            },
        )
        return oauth_flow.build_authorization_url(
            authorization_endpoint=cfg.authorization_endpoint,
            client_id=cfg.client_id,
            redirect_uri=redirect_uri,
            state=st,
            code_challenge=pkce.code_challenge,
            scope=cfg.scope,
            extra_params=cfg.extra_auth_params or None,
        )

    async def store_manual_token(
        self, *, user_id: uuid.UUID, fields: dict[str, str]
    ) -> None:
        if not self.supports_manual:
            raise ValueError(f"provider '{self.key}' does not support manual tokens")
        token = (fields.get("token") or "").strip()
        if not token:
            raise ValueError("token is required")
        # Reject invalid tokens at entry time. Providers without a real liveness
        # check inherit the permissive default (``validate`` → True).
        if not await self.validate(token):
            raise ValueError("Токен недействителен — проверьте и попробуйте снова.")
        factory = await get_session_factory()
        async with factory() as session:
            await OAuthConnectionRepository(session).upsert(
                user_id=user_id,
                provider_key=self.key,
                access_token=token,
                refresh_token=None,
                expires_at=None,
                token_type=self._cfg.auth_header_scheme,
                scope=self._cfg.scope,
                metadata_json={"manual": True},
            )

    # -- use ------------------------------------------------------------------ #

    async def access_token(self, *, user_id: uuid.UUID) -> str:
        factory = await get_session_factory()
        async with factory() as session:
            repo = OAuthConnectionRepository(session)
            row = await repo.get(user_id, self.key)
            if row is None or not row.access_token:
                raise ReauthRequired(self.key, "no token stored")

            if not self._is_expired(row.expires_at):
                return row.access_token

            # Expired. Manual tokens / no refresh token → reauth.
            if not row.refresh_token:
                raise ReauthRequired(self.key, "token expired")

            try:
                token = await oauth_flow.refresh_access_token(
                    token_endpoint=self._cfg.token_endpoint,
                    refresh_token=row.refresh_token,
                    client_id=self._cfg.client_id,
                    client_secret=self._cfg.client_secret,
                    scope=self._cfg.scope,
                )
            except oauth_flow.RefreshError as exc:
                if exc.permanent:
                    raise ReauthRequired(self.key, str(exc)) from exc
                raise

            expires_at = None
            if token.expires_in is not None:
                expires_at = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + token.expires_in,
                    tz=timezone.utc,
                )
            await repo.upsert(
                user_id=user_id,
                provider_key=self.key,
                access_token=token.access_token,
                # Some providers omit refresh_token on refresh → keep the old one.
                refresh_token=token.refresh_token or row.refresh_token,
                expires_at=expires_at,
                token_type=token.token_type or row.token_type or "Bearer",
                scope=token.scope or row.scope,
            )
            return token.access_token

    async def status(self, *, user_id: uuid.UUID) -> ConnectionStatus:
        factory = await get_session_factory()
        async with factory() as session:
            row = await OAuthConnectionRepository(session).get(user_id, self.key)
        if row is None or not row.access_token:
            return ConnectionStatus(status="not_connected")
        if self._is_expired(row.expires_at) and not row.refresh_token:
            return ConnectionStatus(
                status="needs_reauth",
                detail="token expired",
                scope=row.scope,
                token_hint=_mask(row.access_token),
            )
        return ConnectionStatus(
            status="connected",
            scope=row.scope,
            token_hint=_mask(row.access_token),
        )

    # -- helpers -------------------------------------------------------------- #

    @staticmethod
    def _is_expired(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc).timestamp()
        return expires_at.timestamp() - now <= _EXPIRY_LEEWAY_SECONDS
