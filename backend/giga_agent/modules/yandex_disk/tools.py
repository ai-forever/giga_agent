"""Yandex Disk tools — talk to the REST API directly using an OAuth token from
the shared integrations store (provider key ``yandex``)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.core.integrations.errors import ReauthRequired
from giga_agent.core.integrations.registry import YANDEX_PROVIDER_KEY
from giga_agent.core.integrations.service import get_access_token
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

_API_BASE = "https://cloud-api.yandex.net/v1/disk"
_REAUTH_HINT = (
    "Нет доступа к Яндекс.Диску. Скажи пользователю переподключить «Яндекс» в "
    "настройках интеграций."
)


async def _yandex_token(runtime: ToolRuntime) -> str:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    try:
        return await get_access_token(owner_id, YANDEX_PROVIDER_KEY)
    except ReauthRequired as exc:
        raise ValueError(_REAUTH_HINT) from exc


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {token}", "Accept": "application/json"}


@tool(parse_docstring=True)
async def yandex_disk_info(runtime: ToolRuntime) -> dict[str, Any]:
    """Возвращает информацию о Яндекс.Диске пользователя: объём и занятое место."""
    token = await _yandex_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.get(_API_BASE, headers=_headers(token))
        resp.raise_for_status()
        data = resp.json()
    return {
        "total_space": data.get("total_space"),
        "used_space": data.get("used_space"),
        "trash_size": data.get("trash_size"),
    }


@tool(parse_docstring=True)
async def yandex_disk_list(runtime: ToolRuntime, path: str = "/") -> dict[str, Any]:
    """Список файлов и папок по пути на Яндекс.Диске.

    Args:
        path: Путь к папке на Диске. Корень — "/".
    """
    token = await _yandex_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/resources",
            headers=_headers(token),
            params={"path": path, "limit": 100},
        )
        resp.raise_for_status()
        data = resp.json()
    items = (data.get("_embedded") or {}).get("items") or []
    return {
        "path": data.get("path"),
        "items": [
            {
                "name": it.get("name"),
                "type": it.get("type"),
                "path": it.get("path"),
                "size": it.get("size"),
                "modified": it.get("modified"),
            }
            for it in items
        ],
    }


@tool(parse_docstring=True)
async def yandex_disk_download_url(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Возвращает прямую ссылку для скачивания файла с Яндекс.Диска.

    Args:
        path: Путь к файлу на Диске.
    """
    token = await _yandex_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/resources/download",
            headers=_headers(token),
            params={"path": path},
        )
        resp.raise_for_status()
        data = resp.json()
    return {"href": data.get("href")}
