"""OAuth2 (authorization-code + DCR) routes for MCP servers.

The callback is hosted by the backend; the frontend only opens a popup at
``/agent/mcp/servers/{id}/oauth/start`` and listens for the ``mcp_auth_callback``
postMessage emitted by the callback page.

Tokens are stored in the shared connection store (``core_oauth_connections``,
keyed by ``mcp:<server_id>``); the OAuth machinery itself lives in
``giga_agent.core.integrations``.
"""

from __future__ import annotations

import json
import traceback
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.core.integrations import state
from giga_agent.core.integrations.mcp_provider import McpServerProvider
from giga_agent.core.integrations.token_storage import resolve_base_url
from giga_agent.routes._shared.access import fetch_resource_with_read_and_edit

logger = get_logger(__name__)

router = APIRouter(prefix="/servers", tags=["mcp"])


def _callback_html(success: bool, error: str | None = None) -> HTMLResponse:
    payload: dict[str, Any] = {"type": "mcp_auth_callback", "success": success}
    if error:
        payload["error"] = error
    body = f"""<!doctype html><html><body>
<script>
try {{ if (window.opener) window.opener.postMessage({json.dumps(payload)}, "*"); }} catch (e) {{}}
window.close();
</script>
<p>{'Authorization complete. You can close this window.' if success else 'Authorization failed.'}</p>
</body></html>"""
    return HTMLResponse(content=body)


@router.get("/{server_id}/oauth/start", response_model=dict)
async def oauth_start(
    server_id: uuid.UUID,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    repo = McpServerRepository(db)
    server, _ = await fetch_resource_with_read_and_edit(
        resource_id=server_id,
        user_id=current_user.id,
        repository=repo,
        not_found_detail="MCP server not found",
    )
    if (server.auth_type or "").lower() != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server is not configured for OAuth2",
        )

    base_url = resolve_base_url()
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth is not configured (set GIGA_AGENT_BASE_URL)",
        )

    try:
        auth_url = await McpServerProvider(server).authorization_url(
            user_id=current_user.id, db=db, base_url=base_url
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OAuth start failed: {exc}",
        ) from exc

    # Returned as JSON (not a redirect) so the SPA can open the provider URL in a
    # popup directly — a popup navigation cannot carry the bearer auth header.
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
async def oauth_callback(
    db: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = Query(default=None),
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
):
    if error:
        return _callback_html(False, error=error)
    if not code or not state_param:
        return _callback_html(False, error="missing code/state")

    data = await state.pop_oauth_state(
        namespace=state.MCP_STATE_NS, state=state_param
    )
    if not data:
        return _callback_html(False, error="invalid or expired state")

    try:
        await state.finalize_oauth(db, data, code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP OAuth token exchange failed: %s", exc)
        return _callback_html(False, error="token exchange failed")

    server_id = uuid.UUID(data["provider_key"][len("mcp:"):])
    await McpServerRepository.invalidate_tools_cache(server_id)
    return _callback_html(True)
