"""OAuth2 (authorization-code + DCR) routes for MCP servers.

The callback is hosted by the backend; the frontend only opens a popup at
``/agent/mcp/servers/{id}/oauth/start`` and listens for the ``mcp_auth_callback``
postMessage emitted by the callback page.
"""

from __future__ import annotations

import json
import secrets
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from cashews import cache
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from mcp.client.auth import PKCEParameters
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.mcp_server import McpOAuthTokenRepository, McpServerRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.mcp import oauth_flow
from giga_agent.modules.mcp.token_storage import callback_url, resolve_base_url
from giga_agent.routes._shared.access import fetch_resource_with_read_and_edit

logger = get_logger(__name__)

router = APIRouter(prefix="/servers", tags=["mcp"])

_STATE_TTL = "10m"


def _state_key(state: str) -> str:
    return f"mcp:oauth:state:{state}"


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
    redirect_uri = callback_url(base_url)
    settings = server.settings or {}
    scope = settings.get("scope")

    try:
        info = await oauth_flow.discover_auth_server(server.url)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OAuth discovery failed: {exc}",
        ) from exc

    token_repo = McpOAuthTokenRepository(db)
    client_id = settings.get("client_id")
    client_secret = settings.get("client_secret")
    if not client_id:
        if not settings.get("use_dcr", True):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No client_id configured and dynamic registration is disabled",
            )
        try:
            client_info = await oauth_flow.register_client(
                server_url=server.url,
                registration_endpoint=info.registration_endpoint,
                redirect_uri=redirect_uri,
                scope=scope,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Dynamic client registration failed: {exc}",
            ) from exc
        client_id = client_info.client_id
        client_secret = client_info.client_secret
        await token_repo.upsert(
            user_id=current_user.id,
            server_id=server.id,
            client_id=client_id,
            client_secret=client_secret,
        )

    pkce = PKCEParameters.generate()
    state = secrets.token_urlsafe(32)
    await cache.set(
        _state_key(state),
        {
            "user_id": str(current_user.id),
            "server_id": str(server.id),
            "server_url": server.url,
            "code_verifier": pkce.code_verifier,
            "token_endpoint": info.token_endpoint,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "scope": scope,
        },
        expire=_STATE_TTL,
    )

    auth_url = oauth_flow.build_authorization_url(
        authorization_endpoint=info.authorization_endpoint,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=pkce.code_challenge,
        scope=scope,
        server_url=server.url,
    )
    # Returned as JSON (not a redirect) so the SPA can open the provider URL in a
    # popup directly — a popup navigation cannot carry the bearer auth header.
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
async def oauth_callback(
    db: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        return _callback_html(False, error=error)
    if not code or not state:
        return _callback_html(False, error="missing code/state")

    data = await cache.get(_state_key(state))
    if not data:
        return _callback_html(False, error="invalid or expired state")
    await cache.delete(_state_key(state))

    try:
        token = await oauth_flow.exchange_code(
            token_endpoint=data["token_endpoint"],
            code=code,
            code_verifier=data["code_verifier"],
            redirect_uri=data["redirect_uri"],
            client_id=data["client_id"],
            client_secret=data.get("client_secret"),
            server_url=data["server_url"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP OAuth token exchange failed: %s", exc)
        return _callback_html(False, error="token exchange failed")

    expires_at = None
    if token.expires_in is not None:
        expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + token.expires_in,
            tz=timezone.utc,
        )

    server_id = uuid.UUID(data["server_id"])
    await McpOAuthTokenRepository(db).upsert(
        user_id=uuid.UUID(data["user_id"]),
        server_id=server_id,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=expires_at,
        token_type=token.token_type or "Bearer",
        scope=token.scope or data.get("scope"),
        client_id=data["client_id"],
        client_secret=data.get("client_secret"),
    )
    await McpServerRepository.invalidate_tools_cache(server_id)
    return _callback_html(True)
