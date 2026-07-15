"""CRUD + discovery endpoints for backend-managed MCP servers."""

from __future__ import annotations

import re
import traceback
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings

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
from giga_agent.models.oauth_connection import (
    OAuthConnectionRepository,
    mcp_provider_key,
)
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user, require_superuser
from giga_agent.modules.mcp.catalog import (
    CatalogEntry,
    get_entry,
    resolve_oauth_env_settings,
    visible_catalog,
)
from giga_agent.modules.mcp.client import (
    call_server_tool,
    list_server_tools,
    read_server_resource,
)
from giga_agent.modules.mcp.errors import McpAuthRequiredError, McpError
from giga_agent.modules.mcp.local_config import (
    LOCAL_PREFIX,
    disabled_local_names,
    is_local_runtime,
    load_local_servers,
    local_config_path,
    open_local_config_in_editor,
)
from giga_agent.modules.mcp.resolved import ResolvedServer, resolve_db_server
from giga_agent.modules.mcp.tools import _callable_by_app
from giga_agent.routes._shared.access import (
    fetch_resource_with_access_check,
    fetch_resource_with_read_and_edit,
)

router = APIRouter(prefix="/servers", tags=["mcp"])


class CatalogConnectRequest(BaseModel):
    """User-supplied values for a catalog entry's ``requires`` fields."""

    inputs: dict[str, str] | None = None


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
        traceback.print_exc()
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
    # oauth2 token state lives in core_oauth_connections (per user), not settings.
    has_oauth = any((item.auth_type or "").lower() == "oauth2" for item, _ in rows)
    authorized: set[str] = (
        await OAuthConnectionRepository(repo.db).authorized_provider_keys(
            current_user.id
        )
        if has_oauth
        else set()
    )
    return [
        McpServerRepository.to_response(
            item,
            can_edit=can_edit,
            has_token=(
                mcp_provider_key(item.id) in authorized
                if (item.auth_type or "").lower() == "oauth2"
                else None
            ),
        )
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


@router.get("/catalog", response_model=list[CatalogEntry])
async def list_catalog(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    """Curated quick-connect remote MCP servers (read-only templates).

    Entries gated behind env vars (e.g. Google Workspace, which needs
    ``GOOGLE_AUTH_CLIENT_ID``/``GOOGLE_AUTH_CLIENT_SECRET``) are hidden until
    those vars are configured.
    """
    _ = current_user
    return visible_catalog()


@router.post(
    "/catalog/{entry_id}/connect",
    response_model=McpServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_catalog(
    entry_id: str,
    data: CatalogConnectRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    """Create a managed server from a catalog template for the current user.

    Secrets that come from the environment (OAuth client creds) are injected
    here, server-side — they are never sent by or returned to the client.
    """
    entry = get_entry(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog entry not found",
        )

    auth_type = _validate_auth_type(entry.auth_type)
    settings: dict[str, Any] = {}

    # User-supplied fields declared in the entry's `requires` (e.g. bearer key).
    inputs = data.inputs or {}
    for field in entry.requires:
        value = (inputs.get(field.key) or "").strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing required field '{field.key}'",
            )
        settings[field.key] = value

    if auth_type == "oauth2":
        if entry.oauth_scope:
            settings["scope"] = entry.oauth_scope
        env_creds = resolve_oauth_env_settings(entry)
        if env_creds:
            # Pre-registered client → skip dynamic registration.
            settings.update(env_creds)
            settings["use_dcr"] = False
        else:
            settings["use_dcr"] = True

    server = await repo.create(
        owner_id=current_user.id,
        url=entry.url,
        auth_type=auth_type,
        name=entry.name,
        settings=normalize_settings(auth_type, settings),
        is_active=True,
    )

    # OAuth servers need the user to authorize first; only probe the rest.
    tool_count = None
    if auth_type != "oauth2":
        tool_count = await _discover_or_http_error(
            server, user_id=current_user.id, db=repo.db
        )
    return McpServerRepository.to_response(server, can_edit=True, tool_count=tool_count)


@router.get("/local", response_model=list[dict])
async def list_local_servers(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    if not is_local_runtime():
        return []
    disabled = disabled_local_names(current_user.settings)
    return [
        {**_local_to_dict(s), "is_active": s.name not in disabled}
        for s in load_local_servers().values()
    ]


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
    has_token: bool | None = None
    if (server.auth_type or "").lower() == "oauth2":
        conn = await OAuthConnectionRepository(repo.db).get(
            current_user.id, mcp_provider_key(server.id)
        )
        has_token = bool(conn and conn.access_token)
    return McpServerRepository.to_response(
        server, can_edit=can_edit, has_token=has_token
    )


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
    return {
        "ok": tool_count is not None,
        "tool_count": tool_count,
        "auth_required": tool_count is None,
    }


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


# ── MCP Apps (interactive widget) host bridge ───────────────────────────────
# Two endpoints back the frontend host: one serves the widget's ``ui://`` HTML,
# the other proxies the widget's ``tools/call`` to the server (app-scoped only).


class UiToolCallRequest(BaseModel):
    """A widget-originated ``tools/call``, proxied to the MCP server."""

    tool: str
    arguments: dict[str, Any] | None = None


# Recommended CSP to lock a widget's network egress to esm.sh only (the
# isolation a separate domain would otherwise give). NOT applied by default —
# copy this into the GIGA_AGENT_MCP_UI_CSP setting to enable egress restriction.
_RECOMMENDED_MCP_UI_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline' 'unsafe-eval' https://esm.sh; "
    "style-src 'unsafe-inline' https://esm.sh; "
    "img-src data: blob: https://esm.sh; "
    "font-src data: https://esm.sh; "
    "connect-src https://esm.sh"
)
_HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)


def _mcp_ui_csp() -> str | None:
    """Configured widget CSP, or None when egress restriction is disabled."""
    csp = (get_settings().giga_agent_mcp_ui_csp or "").strip()
    return csp or None


def _inject_widget_head(html: str) -> str:
    """Prepend the (optional) CSP <meta> to <head>.

    The widget loads with its own (cross-)origin (allow-same-origin), so real
    localStorage works and no storage shim is needed. The CSP <meta> is only
    added when egress restriction is configured; it comes first so it precedes
    the scripts it governs.
    """
    csp = _mcp_ui_csp()
    if csp is None:
        return html
    meta = f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
    match = _HEAD_OPEN_RE.search(html)
    if match:
        pos = match.end()
        return html[:pos] + meta + html[pos:]
    return meta + html  # no <head> — prepend so it still applies first


async def _resolve_readable_server_ref(
    ref: str,
    *,
    user_id: uuid.UUID,
    repo: McpServerRepository,
) -> ResolvedServer:
    """Resolve a server the user may read, by name / cache_id / UUID, or local.

    Mirrors ``tools-by-name`` resolution so the frontend can pass the
    ``server_id`` (cache_id) carried on the ``mcp_ui`` attachment.
    """
    for server in await repo.get_readable_for_user(user_id):
        candidate = resolve_db_server(server)
        if ref in (candidate.name, candidate.cache_id, str(server.id)):
            return candidate
    # Local servers: match by name OR cache_id. The dict is keyed by name
    # ("local_<ns>"), but the mcp_ui attachment carries cache_id ("local:<ns>"),
    # so a plain .get(ref) would miss when the widget passes the cache_id.
    for candidate in load_local_servers().values():
        if ref in (candidate.name, candidate.cache_id):
            return candidate
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
    )


@router.get("/{server_ref}/ui-resource")
async def get_ui_resource(
    server_ref: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
    uri: str = Query(..., description="The ui:// resource URI to read"),
):
    """Serve an MCP App widget's HTML (``ui://…`` resource) for the iframe host."""
    if not uri.startswith("ui://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only 'ui://' resources may be read here",
        )
    resolved = await _resolve_readable_server_ref(
        server_ref, user_id=current_user.id, repo=repo
    )
    try:
        html, _mime = await read_server_resource(
            resolved, uri, user_id=current_user.id, db=repo.db
        )
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to read UI resource: {exc}",
        ) from exc
    # Served into a sandboxed (opaque-origin) iframe. When egress restriction is
    # configured, the injected CSP <meta> (and header) lock the widget's network
    # without needing a separate domain; otherwise no CSP is applied.
    headers = {"X-Content-Type-Options": "nosniff"}
    csp = _mcp_ui_csp()
    if csp is not None:
        headers["Content-Security-Policy"] = csp
    return Response(
        content=_inject_widget_head(html),
        media_type="text/html; charset=utf-8",
        headers=headers,
    )


@router.post("/{server_ref}/ui-call", response_model=dict)
async def ui_call_tool(
    server_ref: str,
    data: UiToolCallRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    repo: Annotated[McpServerRepository, Depends(get_mcp_repository)],
):
    """Proxy a widget's ``tools/call`` to the server (app-visible tools only).

    Security gate: the widget may only invoke tools the server marks callable by
    apps (``meta.ui.visibility`` containing ``"app"``, or unset). This keeps the
    iframe from reaching arbitrary server tools.
    """
    resolved = await _resolve_readable_server_ref(
        server_ref, user_id=current_user.id, repo=repo
    )

    # Security gate: the widget may only invoke tools the server marks callable
    # by apps. The catalog is served from cache (10m) and, on a miss, lists over
    # a pooled session that the call then reuses — so this is not an extra
    # handshake in practice.
    try:
        catalog = await list_server_tools(resolved, user_id=current_user.id, db=repo.db)
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP discovery failed: {exc}",
        ) from exc

    entry = next((t for t in catalog if t.get("name") == data.tool), None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{data.tool}' not found on this server",
        )
    if not _callable_by_app(entry):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tool '{data.tool}' is not callable by the app",
        )

    try:
        parts, is_error, structured = await call_server_tool(
            resolved,
            data.tool,
            data.arguments or {},
            user_id=current_user.id,
        )
    except McpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"MCP tool call failed: {exc}",
        ) from exc
    return {"content": parts, "structuredContent": structured, "isError": is_error}
