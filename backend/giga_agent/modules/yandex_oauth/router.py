"""HTTP-эндпоинты OAuth-подключения Яндекса (mount: /agent/yandex_oauth).

Флоу:
- POST/GET /start  → (auth) выдаёт authorize_url под scope модуля + подписанный state.
- GET  /callback   → (без auth) Яндекс редиректит сюда; identity берётся из state,
                     токены сохраняются, возвращается HTML, который postMessage'ит
                     опенеру и закрывает popup.
- POST /exchange   → (auth) copy-paste флоу: пользователь вставляет verification code.
- POST /disconnect → (auth) стирает токены модуля.
- GET  /status     → (auth) сконфигурирован ли сервер и какие модули подключены.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from giga_agent.conf import get_settings
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.yandex_oauth import service, state, tokens

router = APIRouter(tags=["yandex_oauth"])


class StartResponse(BaseModel):
    authorize_url: str
    flow: str  # "callback" | "code"


class ExchangeRequest(BaseModel):
    module: str
    code: str


class ModuleRequest(BaseModel):
    module: str


class StatusResponse(BaseModel):
    configured: bool
    callback_available: bool
    connected: dict[str, bool]


def _check_module(module_id: str) -> None:
    if module_id not in service.MODULES:
        raise HTTPException(status_code=400, detail=f"Неизвестный модуль: {module_id}")


def _resolve_flow(requested: str | None) -> bool:
    """Возвращает use_callback. 'callback' требует сконфигурированного redirect_uri;
    при 'auto'/None выбираем callback, если доступен, иначе code."""
    if requested == "code":
        return False
    if requested == "callback":
        if not service.redirect_uri():
            raise HTTPException(
                status_code=400,
                detail="Server-callback недоступен: не задан GIGA_AGENT_BASE_URL "
                "или YANDEX_OAUTH_REDIRECT_URI.",
            )
        return True
    return service.redirect_uri() is not None


@router.get("/start", response_model=StartResponse)
async def start(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    module: str = Query(...),
    flow: str | None = Query(None),
) -> StartResponse:
    _check_module(module)
    if not service.is_configured(module):
        raise HTTPException(
            status_code=400,
            detail="OAuth Яндекса не настроен на сервере "
            "(нет YANDEX_OAUTH_CLIENT_ID / YANDEX_OAUTH_CLIENT_SECRET).",
        )
    use_callback = _resolve_flow(flow)
    flow_name = "callback" if use_callback else "code"
    signed = state.issue_state(
        user_id=str(current_user.id), module_id=module, flow=flow_name
    )
    try:
        url = service.build_authorize_url(module, signed, use_callback=use_callback)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StartResponse(authorize_url=url, flow=flow_name)


def _postmessage_origin() -> str:
    """Конкретный origin для postMessage (никогда "*"): из base_url, иначе из
    redirect_uri (scheme://host[:port]). Сужаем, кому popup отдаёт результат."""
    settings = get_settings()
    base = settings.giga_agent_base_url
    if not base:
        redirect = service.redirect_uri()  # напр. http://localhost:8123/api/...
        if redirect:
            parts = urlsplit(redirect)
            base = f"{parts.scheme}://{parts.netloc}"
    return base or ""


def _callback_html(status: str, module: str, message: str = "") -> str:
    origin = _postmessage_origin()
    # Если конкретный origin неизвестен — JS-null, postMessage не шлётся (не "*").
    target = json.dumps(origin or None)
    safe_msg = message.replace("<", "").replace(">", "").replace('"', "'")
    heading = "Готово!" if status == "connected" else "Не получилось"
    note = (
        "Аккаунт Яндекса подключён. Можно вернуться в чат."
        if status == "connected"
        else f"Ошибка подключения: {safe_msg}"
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>{heading}</title>
<style>body{{font-family:system-ui,sans-serif;background:#0f0f10;color:#eee;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;max-width:340px;padding:24px}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#aaa;font-size:14px;line-height:1.5}}</style>
</head><body><div class="card"><h1>{heading}</h1><p>{note}</p></div>
<script>
try {{
  var target = {target};
  if (window.opener && target) {{
    window.opener.postMessage(
      {{type:"yandex_oauth", status:"{status}", module:"{module}"}}, target);
  }}
}} catch (e) {{}}
setTimeout(function(){{ window.close(); }}, 1200);
</script></body></html>"""


@router.get("/callback")
async def callback(
    code: str | None = Query(None),
    state_param: str | None = Query(None, alias="state"),
    error: str | None = Query(None),
) -> HTMLResponse:
    if error:
        return HTMLResponse(_callback_html("error", "", error))
    if not code or not state_param:
        return HTMLResponse(_callback_html("error", "", "missing code/state"))
    try:
        payload = state.verify_state(state_param)
    except ValueError as exc:
        return HTMLResponse(_callback_html("error", "", str(exc)))

    module = str(payload.get("m", ""))
    if module not in service.MODULES:
        return HTMLResponse(_callback_html("error", module, "unknown module"))
    try:
        user_id = uuid.UUID(str(payload["u"]))
        token_response = await service.exchange_code(
            code, use_callback=True, module_id=module
        )
        await tokens.store_tokens(user_id, module, token_response)
    except Exception as exc:  # noqa: BLE001 — показываем юзеру причину в popup
        return HTMLResponse(_callback_html("error", module, str(exc)))
    return HTMLResponse(_callback_html("connected", module))


@router.post("/exchange")
async def exchange(
    body: ExchangeRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, str]:
    _check_module(body.module)
    try:
        token_response = await service.exchange_code(
            body.code, use_callback=False, module_id=body.module
        )
        await tokens.store_tokens(current_user.id, body.module, token_response)
    except service.YandexOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc.detail)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "connected", "module": body.module}


@router.post("/disconnect")
async def disconnect(
    body: ModuleRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, str]:
    _check_module(body.module)
    await tokens.disconnect(current_user.id, body.module)
    return {"status": "disconnected", "module": body.module}


@router.get("/status", response_model=StatusResponse)
async def status(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> StatusResponse:
    return StatusResponse(
        configured=service.is_configured(),
        callback_available=service.redirect_uri() is not None,
        connected={
            module_id: tokens.is_connected(current_user, module_id)
            for module_id in service.MODULES
        },
    )
