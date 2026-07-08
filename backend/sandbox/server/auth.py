"""Bearer-token authentication for the SandboxAPI Server.

Один статический токен, с которым запускается сервер. Сравнение — constant-time.
Токен принимается двумя способами:
  * заголовок ``Authorization: Bearer <token>`` (основной путь, HTTP и WS);
  * query-параметр ``?token=<token>`` (fallback для WS-клиентов, которые не
    умеют слать заголовки на handshake).
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Query, WebSocket, status

from .config import get_settings


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def _token_ok(candidate: str | None) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(candidate, get_settings().token)


async def require_token(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """FastAPI dependency: 401 если токен неверный/отсутствует."""
    candidate = _extract_bearer(authorization) or token
    if not _token_ok(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def authenticate_websocket(websocket: WebSocket) -> bool:
    """Проверить токен на WS-handshake. Закрывает соединение при неудаче."""
    authorization = websocket.headers.get("authorization")
    candidate = _extract_bearer(authorization) or websocket.query_params.get("token")
    if not _token_ok(candidate):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False
    return True
