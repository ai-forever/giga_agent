"""MCP server records and per-user OAuth tokens.

Backend-managed MCP servers (as opposed to the browser/localhost MCP flow that
lives in ``front/src/components/mcp``). Mirrors the structure of
:mod:`giga_agent.models.connector` (ACL sharing + cashews caching), but the
cashews cache here stores the *tool discovery* payload (shared across
threads/users by ``server_id``) — see the migration plan, decision #5.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from cashews import cache
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Uuid,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from giga_agent.core.db import JSON_VARIANT, Base
from giga_agent.models._acl import ACLResourceRepositoryMixin
from giga_agent.models.oauth_connection import (
    OAuthConnectionRepository,
    mcp_provider_key,
)
from giga_agent.models.resource_permission import (
    ResourcePermissionRepository,
    ResourcePermissionsPayload,
)
from giga_agent.utils.mcp_host import is_local_url

AUTH_TYPES = ("none", "bearer", "oauth2")


class McpServer(Base):
    """A backend-managed MCP server (streamable HTTP transport only)."""

    __tablename__ = "core_mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("core_users.id", name="fk_core_mcp_servers_owner_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    settings: Mapped[dict] = mapped_column(JSON_VARIANT(), default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class McpServerBase(BaseModel):
    name: Optional[str] = None
    url: str
    auth_type: str = "none"
    settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class McpServerCreate(McpServerBase):
    check_connection: bool = True
    permissions: ResourcePermissionsPayload | None = None


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    url: Optional[str] = None
    auth_type: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    check_connection: bool = True


class McpServerResponse(BaseModel):
    """Public representation of a server — NEVER includes raw secrets."""

    id: uuid.UUID
    owner_id: uuid.UUID
    name: Optional[str] = None
    url: str
    auth_type: str
    is_active: bool
    is_local: bool
    has_token: bool = False
    token_hint: Optional[str] = None
    oauth_scope: Optional[str] = None
    use_dcr: bool = False
    tool_count: Optional[int] = None
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime


def normalize_settings(auth_type: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Keep only the known keys for the given ``auth_type`` and drop empties."""
    settings = settings or {}
    if auth_type == "bearer":
        out = {
            "header_name": settings.get("header_name") or "Authorization",
            "scheme": settings.get("scheme", "Bearer"),
            "token": settings.get("token") or "",
        }
        return {k: v for k, v in out.items() if v != ""}
    if auth_type == "oauth2":
        keys = (
            "scope",
            "authorization_server",
            "client_id",
            "client_secret",
            "use_dcr",
        )
        return {
            k: settings[k]
            for k in keys
            if k in settings and settings[k] not in (None, "")
        }
    return {}


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #


class McpServerRepository(ACLResourceRepositoryMixin[McpServer]):
    resource_model = McpServer
    resource_type = "mcp_server"

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def cache_key(server_id: uuid.UUID) -> str:
        """Cache key for the shared tool-discovery payload (decision #5)."""
        return f"mcp_server:tools:{server_id}"

    @staticmethod
    async def invalidate_tools_cache(server_id: uuid.UUID) -> None:
        await cache.delete(McpServerRepository.cache_key(server_id))

    async def get_by_id(self, server_id: uuid.UUID) -> McpServer | None:
        result = await self.db.execute(
            select(McpServer).where(McpServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        only_active: bool = False,
    ) -> list[McpServer]:
        query = select(McpServer).where(McpServer.owner_id == owner_id)
        if only_active:
            query = query.where(McpServer.is_active == True)  # noqa: E712
        query = query.order_by(McpServer.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_readable_for_user(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[McpServer]:
        rows = await self.list_readable_with_edit_for_user(
            user_id=user_id,
            only_active=only_active,
            user_group_ids=user_group_ids,
        )
        return [item for item, _ in rows]

    async def get_by_id_readable(
        self,
        server_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> McpServer | None:
        row = await self.get_by_id_with_access_for_user(
            server_id, user_id=user_id, user_group_ids=user_group_ids
        )
        if row is None:
            return None
        server, can_read, _ = row
        return server if can_read else None

    async def get_by_id_writable(
        self,
        server_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> McpServer | None:
        row = await self.get_by_id_with_access_for_user(
            server_id, user_id=user_id, user_group_ids=user_group_ids
        )
        if row is None:
            return None
        server, _, can_edit = row
        return server if can_edit else None

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        url: str,
        auth_type: str = "none",
        name: str | None = None,
        settings: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> McpServer:
        server = McpServer(
            owner_id=owner_id,
            url=url,
            auth_type=auth_type,
            name=name,
            settings=normalize_settings(auth_type, settings or {}),
            is_active=is_active,
            is_local=is_local_url(url),
        )
        self.db.add(server)
        await self.db.commit()
        await self.db.refresh(server)
        return server

    async def update(self, server: McpServer, **kwargs: Any) -> McpServer:
        if "url" in kwargs and kwargs["url"]:
            kwargs["is_local"] = is_local_url(kwargs["url"])
        for key, value in kwargs.items():
            if hasattr(server, key):
                setattr(server, key, value)
        await self.db.commit()
        await self.db.refresh(server)
        await self.invalidate_tools_cache(server.id)
        return server

    async def delete(self, server: McpServer) -> None:
        server_id = server.id
        await ResourcePermissionRepository(self.db).revoke_all_for_resource(
            resource_type="mcp_server",
            resource_id=server_id,
            no_commit=True,
        )
        # The OAuth connection no longer has an FK to this server (it is keyed by
        # a free-form provider_key), so cascade-delete its tokens explicitly.
        await OAuthConnectionRepository(self.db).delete_for_provider_prefix(
            mcp_provider_key(server_id)
        )
        await self.db.delete(server)
        await self.db.commit()
        await self.invalidate_tools_cache(server_id)

    @staticmethod
    def to_response(
        server: McpServer,
        *,
        can_edit: bool = False,
        tool_count: int | None = None,
    ) -> McpServerResponse:
        settings = server.settings or {}
        return McpServerResponse(
            id=server.id,
            owner_id=server.owner_id,
            name=server.name,
            url=server.url,
            auth_type=server.auth_type,
            is_active=server.is_active,
            is_local=server.is_local,
            has_token=bool(settings.get("token") or settings.get("client_id")),
            token_hint=_mask_secret(settings.get("token")),
            oauth_scope=settings.get("scope"),
            use_dcr=bool(settings.get("use_dcr")),
            tool_count=tool_count,
            can_edit=can_edit,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )
