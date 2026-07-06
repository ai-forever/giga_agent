"""REST Яндекс.Диска для file_browser-виджета: навигация по папкам и публикация
без round-trip через модель. Авторизация — токен текущего пользователя FastAPI
(с авто-refresh через общий OAuth-стор). Удаления здесь нет намеренно: деструктив
идёт через агента с confirm-гейтом.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.integrations.yandex_disk.auth import get_disk_token_for_user
from giga_agent.modules.integrations.yandex_disk.tools import (
    _list_resources,
    _publish_resource,
    _unpublish_resource,
    file_browser_payload,
)

router = APIRouter(tags=["yandex_disk"])


class PublishRequest(BaseModel):
    path: str


async def _token(user: UserShort) -> str:
    try:
        return await get_disk_token_for_user(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _raise_for_disk(exc: httpx.HTTPStatusError) -> Any:
    detail: Any
    try:
        detail = exc.response.json()
    except Exception:  # noqa: BLE001 — тело может быть не-JSON
        detail = exc.response.text or "Ошибка Яндекс.Диска"
    raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc


@router.get("/list")
async def list_dir(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    path: str = "/",
    limit: int = 50,
) -> dict[str, Any]:
    """Содержимое папки — для навигации по клику в виджете."""
    token = await _token(current_user)
    try:
        items = await _list_resources(token, path, limit)
    except httpx.HTTPStatusError as exc:
        _raise_for_disk(exc)
    return file_browser_payload(path, items)


@router.post("/publish")
async def publish(
    body: PublishRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Публикует файл/папку и возвращает публичную ссылку."""
    token = await _token(current_user)
    try:
        public_url = await _publish_resource(token, body.path)
    except httpx.HTTPStatusError as exc:
        _raise_for_disk(exc)
    return {"path": body.path, "public_url": public_url}


@router.post("/unpublish")
async def unpublish(
    body: PublishRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Снимает публикацию файла/папки."""
    token = await _token(current_user)
    try:
        await _unpublish_resource(token, body.path)
    except httpx.HTTPStatusError as exc:
        _raise_for_disk(exc)
    return {"path": body.path, "public_url": None}
