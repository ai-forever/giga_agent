"""Provider-agnostic per-user OAuth connections.

Generalizes the former ``core_mcp_oauth_tokens`` table: instead of a hard FK to
``core_mcp_servers``, a connection is keyed by a free-form ``provider_key``
string. MCP servers use ``"mcp:<server_id>"``; native integrations (Yandex,
GitHub, ...) use their provider id (``"yandex"``, ``"github"``).

The same store backs both the MCP client (call-time OAuth refresh) and native
agent modules that talk to a service's REST API directly. Rows are never
serialized into any API response (they hold raw secrets).

Because the MCP FK (with ``ondelete=CASCADE``) is gone, MCP server deletion must
now explicitly drop the matching connection — see
:meth:`McpServerRepository.delete` and
:meth:`OAuthConnectionRepository.delete_for_provider_prefix`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import JSON_VARIANT, Base


def mcp_provider_key(server_id: uuid.UUID | str) -> str:
    """Connection key for an MCP server."""
    return f"mcp:{server_id}"


class OAuthConnection(Base):
    """Per-user OAuth tokens + client creds for an integration provider.

    Never serialized into any API response.
    """

    __tablename__ = "core_oauth_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_key", name="uq_oauth_conn_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Nullable: a row may hold only DCR client creds during the auth flow,
    # before any access token has been issued.
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_type: Mapped[str | None] = mapped_column(String(64), default="Bearer")
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider-specific extras: discovered endpoints for static providers,
    # ``{"manual": true}`` for manually-entered tokens (refresh is never tried).
    metadata_json: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


class OAuthConnectionRepository:
    """Plain (non-ACL) repository for per-user OAuth connections."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, user_id: uuid.UUID, provider_key: str
    ) -> OAuthConnection | None:
        result = await self.db.execute(
            select(OAuthConnection).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.provider_key == provider_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[OAuthConnection]:
        result = await self.db.execute(
            select(OAuthConnection).where(OAuthConnection.user_id == user_id)
        )
        return list(result.scalars().all())

    async def authorized_provider_keys(self, user_id: uuid.UUID) -> set[str]:
        """Provider keys for which *user_id* has a usable access token.

        Rows holding only DCR client creds (``access_token IS NULL``) are excluded
        — authorization is not yet complete for those.
        """
        result = await self.db.execute(
            select(OAuthConnection.provider_key).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.access_token.is_not(None),
            )
        )
        return set(result.scalars().all())

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        provider_key: str,
        **fields: Any,
    ) -> OAuthConnection:
        conn = await self.get(user_id, provider_key)
        if conn is None:
            conn = OAuthConnection(user_id=user_id, provider_key=provider_key)
            self.db.add(conn)
        for key, value in fields.items():
            if hasattr(conn, key):
                setattr(conn, key, value)
        await self.db.commit()
        await self.db.refresh(conn)
        return conn

    async def delete(self, user_id: uuid.UUID, provider_key: str) -> None:
        conn = await self.get(user_id, provider_key)
        if conn is not None:
            await self.db.delete(conn)
            await self.db.commit()

    async def delete_for_provider_prefix(self, prefix: str) -> None:
        """Delete every connection whose ``provider_key`` starts with ``prefix``.

        Replaces the old FK ``ondelete=CASCADE``: e.g. when an MCP server is
        deleted, ``delete_for_provider_prefix("mcp:<server_id>")`` drops the
        tokens of all users for that server.
        """
        result = await self.db.execute(
            select(OAuthConnection).where(
                OAuthConnection.provider_key.like(f"{prefix}%")
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return
        for conn in rows:
            await self.db.delete(conn)
        await self.db.commit()
