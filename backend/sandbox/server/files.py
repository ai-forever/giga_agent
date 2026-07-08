"""Streaming file endpoints.

Всё чтение/запись — потоком с чанками (+ поддержка HTTP ``Range``), а не
``exec cat`` / base64-в-одну-команду, как в local_docker. Это устраняет OOM на
больших файлах: сервер никогда не держит файл целиком в памяти.

Путь — абсолютный внутри песочницы. Граница безопасности — сама песочница
(контейнер/VM), поэтому произвольные пути внутри неё легитимны.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .auth import require_token
from .config import get_settings
from .models import DirEntry, DirListing, FileStat, WrittenResponse

router = APIRouter(prefix="/v1/files", tags=["files"], dependencies=[Depends(require_token)])


def _resolve(path: str) -> Path:
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="path is required")
    return Path(path).expanduser()


async def _stream_file(path: Path, start: int, end: int, chunk_size: int) -> AsyncIterator[bytes]:
    """Отдать [start, end) включительно-эксклюзивно по границам чанка."""
    remaining = end - start
    async with aiofiles.open(path, "rb") as handle:
        await handle.seek(start)
        while remaining > 0:
            chunk = await handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _parse_range(range_header: str | None, size: int) -> tuple[int, int] | None:
    """Вернуть (start, end_exclusive) для одиночного bytes-range или None."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes=") :].split(",")[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    if start_s == "":  # суффиксный диапазон: bytes=-N
        n = int(end_s)
        if n <= 0:
            return (0, 0)
        return (max(0, size - n), size)
    start = int(start_s)
    end = int(end_s) + 1 if end_s else size
    end = min(end, size)
    if start >= size or start < 0 or start >= end:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{size}"},
            detail="Requested range not satisfiable",
        )
    return (start, end)


@router.get("")
async def read_file(request: Request, path: str = Query(...)):
    local = _resolve(path)
    if not local.exists() or not local.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    settings = get_settings()
    size = local.stat().st_size
    media_type = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
    inline = local.suffix.lower() in {".html", ".htm"}
    disposition = "inline" if inline else "attachment"
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{local.name}"',
    }

    rng = _parse_range(request.headers.get("range"), size)
    if rng is not None:
        start, end = rng
        headers = {
            **base_headers,
            "Content-Range": f"bytes {start}-{end - 1}/{size}",
            "Content-Length": str(end - start),
        }
        return StreamingResponse(
            _stream_file(local, start, end, settings.stream_chunk_size),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media_type,
            headers=headers,
        )

    headers = {**base_headers, "Content-Length": str(size)}
    return StreamingResponse(
        _stream_file(local, 0, size, settings.stream_chunk_size),
        media_type=media_type,
        headers=headers,
    )


@router.put("", response_model=WrittenResponse)
async def write_file(request: Request, path: str = Query(...)):
    local = _resolve(path)
    local.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with aiofiles.open(local, "wb") as handle:
        async for chunk in request.stream():
            if chunk:
                await handle.write(chunk)
                written += len(chunk)
    return WrittenResponse(path=str(local), size=written)


@router.head("")
async def head_file(path: str = Query(...)):
    local = _resolve(path)
    if not local.exists() or not local.is_file():
        return Response(status_code=404)
    size = local.stat().st_size
    return Response(
        status_code=200,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
    )


@router.get("/stat", response_model=FileStat)
async def stat_file(path: str = Query(...)):
    local = _resolve(path)
    if not local.exists():
        return FileStat(path=str(local), exists=False)
    st = local.stat()
    return FileStat(
        path=str(local),
        exists=True,
        is_dir=local.is_dir(),
        size=st.st_size,
        modified_at=st.st_mtime,
    )


@router.delete("")
async def delete_file(path: str = Query(...), recursive: bool = Query(False)):
    local = _resolve(path)
    if local.is_dir():
        if not recursive:
            raise HTTPException(
                status_code=400,
                detail="path is a directory; pass recursive=true to delete it",
            )
        shutil.rmtree(local, ignore_errors=True)
        return JSONResponse({"path": str(local), "deleted": True})
    try:
        await aiofiles.os.remove(local)
    except FileNotFoundError:
        pass
    return JSONResponse({"path": str(local), "deleted": True})


@router.get("/list", response_model=DirListing)
async def list_dir(path: str = Query(...)):
    local = _resolve(path)
    if not local.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    entries: list[DirEntry] = []
    with os.scandir(local) as it:
        for e in it:
            try:
                is_dir = e.is_dir()
                size = 0 if is_dir else e.stat().st_size
            except OSError:
                continue
            entries.append(DirEntry(name=e.name, is_dir=is_dir, size=size))
    entries.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return DirListing(path=str(local), entries=entries)


@router.post("/mkdir")
async def mkdir(path: str = Query(...)):
    local = _resolve(path)
    local.mkdir(parents=True, exist_ok=True)
    return JSONResponse({"path": str(local), "created": True})
