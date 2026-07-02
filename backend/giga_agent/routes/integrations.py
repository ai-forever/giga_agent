"""Generic integrations API: list providers, connect (OAuth or manual), disconnect.

MCP servers keep their own routes (``modules/mcp/api/oauth.py``); this router
serves native static/manual providers (Yandex, GitHub, ...).
"""

from __future__ import annotations

import json
import traceback
import uuid
from typing import Annotated, Any

from cashews import cache
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.core.integrations import state
from giga_agent.core.integrations.base import IntegrationProvider
from giga_agent.core.integrations.registry import (
    get_static_provider,
    static_providers,
)
from giga_agent.core.integrations.token_storage import resolve_base_url

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


class ManualFieldResponse(BaseModel):
    key: str
    label: str
    secret: bool = True
    placeholder: str | None = None


class ProviderResponse(BaseModel):
    key: str
    label: str
    icon: str | None = None
    auth_kind: str
    status: str
    scope: str | None = None
    token_hint: str | None = None
    manual_fields: list[ManualFieldResponse] = []


def _callback_html(success: bool, provider_key: str | None, error: str | None):
    payload: dict[str, Any] = {
        "type": "integration_auth_callback",
        "success": success,
    }
    if provider_key:
        payload["provider_key"] = provider_key
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


async def _to_response(
    provider: IntegrationProvider, user_id: uuid.UUID
) -> ProviderResponse:
    st = await provider.status(user_id=user_id)
    info = provider.info()
    return ProviderResponse(
        key=info.key,
        label=info.label,
        icon=info.icon,
        auth_kind=info.auth_kind,
        status=st.status,
        scope=st.scope,
        token_hint=st.token_hint,
        manual_fields=[
            ManualFieldResponse(
                key=f.key, label=f.label, secret=f.secret, placeholder=f.placeholder
            )
            for f in info.manual_fields
        ],
    )


def _invalidate_modules_cache(user_id: uuid.UUID) -> Any:
    # Module availability depends on connection status; drop the cached list.
    return cache.delete(f"modules:user:{user_id}")


@router.get("", response_model=list[ProviderResponse])
async def list_integrations(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    providers = static_providers()
    return [
        await _to_response(provider, current_user.id)
        for provider in providers.values()
    ]


@router.get("/{key}/oauth/start", response_model=dict)
async def oauth_start(
    key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    provider = get_static_provider(key)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not provider.supports_oauth:
        raise HTTPException(
            status_code=400, detail="Provider does not support OAuth"
        )
    base_url = resolve_base_url()
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="OAuth is not configured (set GIGA_AGENT_BASE_URL)",
        )
    try:
        auth_url = await provider.authorization_url(
            user_id=current_user.id, db=db, base_url=base_url
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OAuth start failed: {exc}",
        ) from exc
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
async def oauth_callback(
    db: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = Query(default=None),
    state_param: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
):
    if error:
        return _callback_html(False, None, error)
    if not code or not state_param:
        return _callback_html(False, None, "missing code/state")
    data = await state.pop_oauth_state(
        namespace=state.INTEGRATIONS_STATE_NS, state=state_param
    )
    if not data:
        return _callback_html(False, None, "invalid or expired state")
    provider_key = data.get("provider_key")
    try:
        user_id = await state.finalize_oauth(db, data, code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("integration OAuth token exchange failed: %s", exc)
        return _callback_html(False, provider_key, "token exchange failed")
    await _invalidate_modules_cache(user_id)
    return _callback_html(True, provider_key, None)


@router.post("/{key}/token", response_model=ProviderResponse)
async def store_manual_token(
    key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    fields: dict[str, str] = Body(..., embed=True),
):
    provider = get_static_provider(key)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not provider.supports_manual:
        raise HTTPException(
            status_code=400, detail="Provider does not support manual tokens"
        )
    try:
        await provider.store_manual_token(user_id=current_user.id, fields=fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _invalidate_modules_cache(current_user.id)
    return await _to_response(provider, current_user.id)


@router.delete("/{key}", status_code=204)
async def disconnect_integration(
    key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    provider = get_static_provider(key)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    await provider.disconnect(user_id=current_user.id)
    await _invalidate_modules_cache(current_user.id)
