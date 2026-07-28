from __future__ import annotations

from typing import Any

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.core.agent.tool_policy import (
    ToolConfirmation,
    ToolEffect,
    tool_extras,
)
from giga_agent.core.agent.tool_results import build_widget_tool_message
from giga_agent.modules.integrations.widget_hint import with_widget_note
from giga_agent.modules.integrations.yandex_disk.auth import get_disk_token

DISK_API = "https://cloud-api.yandex.net/v1/disk"

# Максимальный размер текстового файла, который тул вернёт прямо в контекст модели.
# Большие/бинарные файлы лучше обрабатывать через sandbox (см. README модуля).
MAX_READ_BYTES = 100_000


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {token}", "Accept": "application/json"}


PROVIDER = "yandex_disk"
# Маркер pushed-в-результат виджета (фронт рендерит file_browser-кит по нему).
FILE_BROWSER_WIDGET = "file_browser"


def _trim_resource(item: dict[str, Any]) -> dict[str, Any]:
    """Оставляет только поля, полезные модели, чтобы не забивать контекст."""
    keys = ("name", "path", "type", "mime_type", "size", "modified", "public_url")
    return {k: item[k] for k in keys if k in item}


async def _list_resources(token: str, path: str, limit: int) -> list[dict[str, Any]]:
    """Сырой список ресурсов директории (общий для тула и REST виджета)."""
    limit = min(max(limit, 1), 100)
    params = {
        "path": path,
        "limit": limit,
        "fields": "_embedded.items.name,_embedded.items.path,_embedded.items.type,"
        "_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,"
        "_embedded.items.public_url",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DISK_API}/resources", headers=_auth_headers(token), params=params
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("_embedded", {}).get("items", [])


def file_browser_payload(path: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Нормализованный payload браузера: маркер виджета + provider + записи.

    Папки — первыми, затем по имени. Фронт рендерит это китом file_browser,
    маршрутизация по `widget`, как у трекера (provider-agnostic канал).
    """
    entries = [_trim_resource(i) for i in items]
    entries.sort(key=lambda e: (e.get("type") != "dir", (e.get("name") or "").lower()))
    return {
        "widget": FILE_BROWSER_WIDGET,
        "provider": PROVIDER,
        "path": path,
        "entries": entries,
    }


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def disk_list_files(
    runtime: ToolRuntime,
    path: str = "/",
    limit: int = 50,
) -> dict[str, Any]:
    """Возвращает список файлов и папок в директории Яндекс.Диска.

    Args:
        path: Путь к папке на Диске. Корень — "/". Например "/Документы".
        limit: Сколько элементов вернуть (максимум 100).
    """
    token = await get_disk_token(runtime)
    items = await _list_resources(token, path, limit)
    return build_widget_tool_message(
        with_widget_note(file_browser_payload(path, items), runtime), runtime=runtime
    )


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def disk_read_text(runtime: ToolRuntime, path: str) -> str:
    """Скачивает текстовый файл с Яндекс.Диска и возвращает его содержимое.

    Подходит для текстовых файлов (txt, csv, md, json). Для больших или
    бинарных файлов используйте обработку через sandbox.

    Args:
        path: Путь к файлу на Диске, например "/Документы/notes.txt".
    """
    token = await get_disk_token(runtime)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        meta = await client.get(
            f"{DISK_API}/resources/download",
            headers=_auth_headers(token),
            params={"path": path},
        )
        meta.raise_for_status()
        href = meta.json()["href"]
        file_resp = await client.get(href, headers=_auth_headers(token))
        file_resp.raise_for_status()
        content = file_resp.content
    if len(content) > MAX_READ_BYTES:
        return (
            f"Файл слишком большой ({len(content)} байт) для прямого чтения. "
            "Обработайте его через sandbox."
        )
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return "Файл не является текстовым (UTF-8). Обработайте его через sandbox."


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.WRITE))
async def disk_create_folder(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Создаёт новую папку (директорию) на Яндекс.Диске.

    Используй именно этот инструмент для создания папок. Для создания файла
    используй disk_upload_text — это разные операции.

    Args:
        path: Путь создаваемой папки, например "/Документы/Отчёты".
    """
    token = await get_disk_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{DISK_API}/resources",
            headers=_auth_headers(token),
            params={"path": path},
        )
        if resp.status_code == 409:
            return {"status": "exists", "path": path}
        resp.raise_for_status()
    return {"status": "created", "path": path}


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.CONDITIONAL,
    ),
)
async def disk_upload_text(
    runtime: ToolRuntime,
    path: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Загружает текстовое содержимое в файл на Яндекс.Диске.

    Args:
        path: Путь, куда сохранить файл, например "/Документы/report.md".
        content: Текстовое содержимое файла.
        overwrite: Перезаписать ли файл, если он уже существует (по умолчанию нет).
    """
    token = await get_disk_token(runtime)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        meta = await client.get(
            f"{DISK_API}/resources/upload",
            headers=_auth_headers(token),
            params={"path": path, "overwrite": str(overwrite).lower()},
        )
        meta.raise_for_status()
        href = meta.json()["href"]
        put_resp = await client.put(href, content=content.encode("utf-8"))
        put_resp.raise_for_status()
    return {"status": "uploaded", "path": path}


async def _publish_resource(token: str, path: str) -> str | None:
    """Публикует ресурс и возвращает публичную ссылку (общий для тула и REST)."""
    async with httpx.AsyncClient() as client:
        pub = await client.put(
            f"{DISK_API}/resources/publish",
            headers=_auth_headers(token),
            params={"path": path},
        )
        pub.raise_for_status()
        meta = await client.get(
            f"{DISK_API}/resources",
            headers=_auth_headers(token),
            params={"path": path, "fields": "name,path,public_url"},
        )
        meta.raise_for_status()
        return meta.json().get("public_url")


async def _unpublish_resource(token: str, path: str) -> None:
    """Снимает публикацию ресурса (общий для тула и REST)."""
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{DISK_API}/resources/unpublish",
            headers=_auth_headers(token),
            params={"path": path},
        )
        resp.raise_for_status()


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.ALWAYS,
    ),
)
async def disk_publish(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Делает файл или папку публичными и возвращает публичную ссылку.

    Args:
        path: Путь к файлу или папке на Диске.
    """
    token = await get_disk_token(runtime)
    public_url = await _publish_resource(token, path)
    return {"path": path, "public_url": public_url}


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.WRITE))
async def disk_unpublish(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Снимает публикацию: файл/папка перестаёт быть доступным по ссылке.

    Args:
        path: Путь к файлу или папке на Диске.
    """
    token = await get_disk_token(runtime)
    await _unpublish_resource(token, path)
    return {"status": "unpublished", "path": path}


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.DESTRUCTIVE,
        confirmation=ToolConfirmation.ALWAYS,
    ),
)
async def disk_delete(
    runtime: ToolRuntime,
    path: str,
    permanently: bool = False,
) -> dict[str, Any]:
    """Удаляет файл или папку на Яндекс.Диске. Используйте осторожно.

    Вызывайте только при явной просьбе пользователя удалить файл. По умолчанию
    объект перемещается в Корзину, а не уничтожается безвозвратно.

    Args:
        path: Путь к удаляемому файлу или папке.
        permanently: Удалить безвозвратно, минуя Корзину (по умолчанию нет).
    """
    token = await get_disk_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{DISK_API}/resources",
            headers=_auth_headers(token),
            params={"path": path, "permanently": str(permanently).lower()},
        )
        resp.raise_for_status()
    return {"status": "deleted", "path": path, "permanently": permanently}
