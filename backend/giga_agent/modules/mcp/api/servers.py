"""CRUD + discovery endpoints for backend-managed MCP servers."""

from __future__ import annotations

import traceback
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.models.mcp_server import (
    AUTH_TYPES,
    McpServer,
    McpServerCreate,
    McpServerRepository,
    McpServerResponse,
    McpServerUpdate,
    normalize_settings,
)
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.modules.mcp.client import list_server_tools
from giga_agent.modules.mcp.errors import McpAuthRequiredError, McpError
from giga_agent.modules.mcp.local_config import (
    LOCAL_PREFIX,
    is_local_runtime,
    load_local_servers,
    local_config_path,
    open_local_config_in_editor,
)
from giga_agent.modules.mcp.resolved import ResolvedServer, resolve_db_server
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)

router = APIRouter(prefix="/servers", tags=["mcp"])


async def get_mcp_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> McpServerRepository:
    return McpServerRepository(db)


def _validate_auth_type(auth_type: str) -> str:
    auth_type = (auth_type or "none").lower()
    if auth_type not in AUTH_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown auth_type '{auth_type}'. Available: {list(AUTH_TYPES)}",
        )
    return auth_type


async def _discover_or_http_error(
    server: McpServer,
    *,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> int | None:
    """Run discovery; return tool count, or None when auth is required.

    Raises HTTP 422 on hard connection failures (but not for OAuth servers that
    simply have no token yet).
    """
    try:
        tools = await list_server_tools(
            resolve_db_server(server), user_id=user_id, db=db, force_refresh=True
        )
        return len(tools)
    except McpAuthRequiredError:
        return None
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP connection check failed: {exc}",
        ) from exc


@router.get("", response_model=list[McpServerResponse])
async def list_servers(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
    only_active: bool = Query(False, description="Only active servers"),
):
    rows = await repo.list_readable_with_edit_for_user(
        user_id=current_user.id,
        only_active=only_active,
    )
    return [
        McpServerRepository.to_response(item, can_edit=can_edit)
        for item, can_edit in rows
    ]


@router.post("", response_model=McpServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    data: McpServerCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    if data.permissions is not None:
        require_superuser(current_user)

    if (data.name or "").lower().startswith(LOCAL_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Server name must not start with '{LOCAL_PREFIX}' (reserved for local servers)",
        )

    auth_type = _validate_auth_type(data.auth_type)
    server = await repo.create(
        owner_id=current_user.id,
        url=data.url,
        auth_type=auth_type,
        name=data.name,
        settings=normalize_settings(auth_type, data.settings),
        is_active=data.is_active,
    )

    if data.permissions is not None:
        await ResourcePermissionRepository(repo.db).set_read_acl(
            resource_type="mcp_server",
            resource_id=server.id,
            read_user_ids=data.permissions.read_user_ids,
            read_group_ids=data.permissions.read_group_ids,
            public_read=data.permissions.public_read,
        )

    tool_count = None
    if data.check_connection:
        tool_count = await _discover_or_http_error(
            server, user_id=current_user.id, db=repo.db
        )
    return McpServerRepository.to_response(server, can_edit=True, tool_count=tool_count)


# NOTE: literal-path routes must be declared BEFORE the parametrized
# ``/{server_id}`` routes, otherwise "local", "local-config", etc. get captured
# as a server_id and fail UUID validation.


def _local_to_dict(s: ResolvedServer) -> dict[str, Any]:
    return {
        "id": s.name,
        "name": s.name,
        "transport": s.transport,
        "url": s.url,
        "command": s.command,
        "is_local": s.is_local,
        "source": "file",
        "auth_type": s.auth_type,
    }


@router.get("/local", response_model=list[dict])
async def list_local_servers(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    if not is_local_runtime():
        return []
    return [_local_to_dict(s) for s in load_local_servers().values()]


@router.get("/local-config", response_model=dict)
async def get_local_config(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    path = local_config_path()
    return {
        "runtime_local": is_local_runtime(),
        "path": str(path),
        "exists": path.exists(),
    }


@router.post("/local-config/open", response_model=dict)
async def open_local_config(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    _ = current_user
    if not is_local_runtime():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Local MCP config is only available in local runtime",
        )
    try:
        path = open_local_config_in_editor()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to open config: {exc}",
        ) from exc
    return {"path": str(path)}


@router.get("/tools-by-name/{name}", response_model=dict)
async def tools_by_name(
    name: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    """Tools for any server (DB or local file) by its model-facing name."""
    resolved: ResolvedServer | None = None
    for server in await repo.get_readable_for_user(current_user.id):
        candidate = resolve_db_server(server)
        if candidate.name == name or candidate.cache_id == name:
            resolved = candidate
            break
    if resolved is None:
        resolved = load_local_servers().get(name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
        )
    try:
        tools = await list_server_tools(resolved, user_id=current_user.id)
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP discovery failed: {exc}",
        ) from exc
    return {"tools": tools, "tool_count": len(tools)}


@router.get("/{server_id}", response_model=McpServerResponse)
async def get_server(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server, can_edit = await fetch_resource_with_read_and_edit(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
    )
    return McpServerRepository.to_response(server, can_edit=can_edit)


@router.patch("/{server_id}", response_model=McpServerResponse)
async def patch_server(
    server_id: uuid.UUID,
    data: McpServerUpdate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server = await fetch_resource_with_access_check(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
        require_edit=True,
    )

    update: dict[str, Any] = {}
    if "name" in data.model_fields_set:
        update["name"] = data.name
    if "url" in data.model_fields_set and data.url:
        update["url"] = data.url
    if "is_active" in data.model_fields_set and data.is_active is not None:
        update["is_active"] = data.is_active

    effective_auth = server.auth_type
    if "auth_type" in data.model_fields_set and data.auth_type:
        effective_auth = _validate_auth_type(data.auth_type)
        update["auth_type"] = effective_auth

    if "settings" in data.model_fields_set and data.settings is not None:
        update["settings"] = normalize_settings(effective_auth, data.settings)
    elif "auth_type" in data.model_fields_set:
        # Re-normalize existing settings under the new auth type.
        update["settings"] = normalize_settings(effective_auth, server.settings or {})

    if update:
        server = await repo.update(server, **update)

    tool_count = None
    if data.check_connection and ("url" in update or "settings" in update):
        tool_count = await _discover_or_http_error(
            server, user_id=current_user.id, db=repo.db
        )
    return McpServerRepository.to_response(server, can_edit=True, tool_count=tool_count)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server = await fetch_resource_with_access_check(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
        require_edit=True,
    )
    await repo.delete(server)


@router.post("/{server_id}/test-connection", response_model=dict)
async def test_connection(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server, _ = await fetch_resource_with_read_and_edit(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
    )
    tool_count = await _discover_or_http_error(
        server, user_id=current_user.id, db=repo.db
    )
    return {"ok": tool_count is not None, "tool_count": tool_count, "auth_required": tool_count is None}


@router.post("/{server_id}/refresh-tools", response_model=dict)
async def refresh_tools(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server, _ = await fetch_resource_with_read_and_edit(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
    )
    await McpServerRepository.invalidate_tools_cache(server.id)
    try:
        tools = await list_server_tools(
            resolve_db_server(server),
            user_id=current_user.id,
            db=repo.db,
            force_refresh=True,
        )
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP discovery failed: {exc}",
        ) from exc
    return {"tools": tools, "tool_count": len(tools)}


@router.get("/{server_id}/tools", response_model=dict)
async def get_server_tools(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    server, _ = await fetch_resource_with_read_and_edit(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
    )
    try:
        tools = await list_server_tools(
            resolve_db_server(server), user_id=current_user.id, db=repo.db
        )
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP discovery failed: {exc}",
        ) from exc
    return {"tools": tools, "tool_count": len(tools)}


