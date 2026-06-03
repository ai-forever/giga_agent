from __future__ import annotations

from typing import Any

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.modules.yandex_disk.auth import get_valid_token

DISK_API = "https://cloud-api.yandex.net/v1/disk"

# Максимальный размер текстового файла, который тул вернёт прямо в контекст модели.
# Большие/бинарные файлы лучше обрабатывать через sandbox (см. README модуля).
MAX_READ_BYTES = 100_000


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {token}", "Accept": "application/json"}


def _trim_resource(item: dict[str, Any]) -> dict[str, Any]:
    """Оставляет только поля, полезные модели, чтобы не забивать контекст."""
    keys = ("name", "path", "type", "mime_type", "size", "modified", "public_url")
    return {k: item[k] for k in keys if k in item}


@tool(parse_docstring=True)
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
    if limit > 100:
        limit = 100
    token = await get_valid_token(runtime)
    params = {"path": path, "limit": limit, "fields": "_embedded.items.name,"
              "_embedded.items.path,_embedded.items.type,_embedded.items.mime_type,"
              "_embedded.items.size,_embedded.items.modified"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DISK_API}/resources", headers=_auth_headers(token), params=params
        )
        resp.raise_for_status()
        data = resp.json()
    items = data.get("_embedded", {}).get("items", [])
    return {"path": path, "items": [_trim_resource(i) for i in items]}


@tool(parse_docstring=True)
async def disk_read_text(runtime: ToolRuntime, path: str) -> str:
    """Скачивает текстовый файл с Яндекс.Диска и возвращает его содержимое.

    Подходит для текстовых файлов (txt, csv, md, json). Для больших или
    бинарных файлов используйте обработку через sandbox.

    Args:
        path: Путь к файлу на Диске, например "/Документы/notes.txt".
    """
    token = await get_valid_token(runtime)
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


@tool(parse_docstring=True)
async def disk_create_folder(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Создаёт новую папку (директорию) на Яндекс.Диске.

    Используй именно этот инструмент для создания папок. Для создания файла
    используй disk_upload_text — это разные операции.

    Args:
        path: Путь создаваемой папки, например "/Документы/Отчёты".
    """
    token = await get_valid_token(runtime)
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


@tool(parse_docstring=True)
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
    token = await get_valid_token(runtime)
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


@tool(parse_docstring=True)
async def disk_publish(runtime: ToolRuntime, path: str) -> dict[str, Any]:
    """Делает файл или папку публичными и возвращает публичную ссылку.

    Args:
        path: Путь к файлу или папке на Диске.
    """
    token = await get_valid_token(runtime)
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
        data = meta.json()
    return {"path": path, "public_url": data.get("public_url")}


@tool(parse_docstring=True)
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
    token = await get_valid_token(runtime)
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{DISK_API}/resources",
            headers=_auth_headers(token),
            params={"path": path, "permanently": str(permanently).lower()},
        )
        resp.raise_for_status()
    return {"status": "deleted", "path": path, "permanently": permanently}
