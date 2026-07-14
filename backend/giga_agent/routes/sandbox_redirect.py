"""Same-origin entrypoint for a sandbox port in cross-domain deployments.

When the app and the sandboxes live on different domains (app on
``GIGA_AGENT_BASE_URL``, sandboxes on ``GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE``),
``open_port`` hands out a clean link on the app domain instead of the raw
sandbox URL. Opening it here (same-origin with the app → the session cookie is
sent) verifies the caller owns the sandbox, mints a port-scoped capability
token, and 302-redirects to
``https://{port}-sandbox-{hex}.{redirect_base}/?__sbx=<token>``. The sandbox
domain then exchanges ``__sbx`` for a host-only cookie via the existing
``grant_sandbox_access`` flow.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session
from giga_agent.models.sandbox import SandboxRepository
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import _parse_sandbox_id_hex, get_current_active_user
from giga_agent.sandbox.access import (
    append_sandbox_access_token_to_url,
    mint_sandbox_access_token,
)

router = APIRouter(tags=["sandbox"])


@router.get("/sandbox-redirect/{sandbox_id_hex}/{port}")
async def redirect_sandbox_port(
    sandbox_id_hex: str,
    port: int,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    redirect_base = get_settings().giga_agent_sandbox_port_redirect_base
    if not redirect_base:
        # Mode disabled — the link should never have been generated.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    sandbox_id = _parse_sandbox_id_hex(sandbox_id_hex)

    owner_id = await SandboxRepository(db).get_owner_id_by_sandbox_cached(sandbox_id)
    if owner_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    token = await mint_sandbox_access_token(sandbox_id_hex, port)
    target = f"https://{port}-sandbox-{sandbox_id_hex}.{redirect_base}/"
    target = append_sandbox_access_token_to_url(target, token)
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
