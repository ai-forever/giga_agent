"""Async client for the SandboxAPI Server.

Реализует три поверхности контракта поверх HTTP/WS сервера:
  * run_code — WebSocket-стриминг с двунаправленным stdin (asend);
  * shell — run/await/list/kill;
  * файлы НЕ-persisted путей песочницы — read (stream)/write/delete/exists.

Формат WS-чанков совпадает с giga_agent.sandbox.jupyter.run_code, поэтому
маппинг на контракт тривиален.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import websockets

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.base import ContentResult, FileReadResult, StreamResult
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellRunResult

logger = get_logger(__name__)

_WS_MAX_SIZE = 32 * 1024 * 1024
_STREAM_CHUNK = 1024 * 1024
# Потолок для служебного read_file_bytes (метаданные и мелкие чтения).
_READ_BYTES_CAP = 32 * 1024 * 1024
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)


class SandboxAPIError(RuntimeError):
    pass


class SandboxAPIClient:
    """Stateless-ish клиент: держит base_url+token, открывает сессию/сокет
    на каждую операцию (как это делает JupyterSandbox)."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _ws_url(self, path: str) -> str:
        ws_base = self._base_url.replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1
        )
        return f"{ws_base}{path}"

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers=self._headers, timeout=_REQUEST_TIMEOUT)

    # ------------------------------------------------------------------ #
    # health
    # ------------------------------------------------------------------ #

    async def is_up(self) -> bool:
        try:
            async with self._session() as session:
                async with session.get(
                    self._url("/healthz"), timeout=aiohttp.ClientTimeout(total=5)
                ) as r:
                    return r.status == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # run_code (WebSocket)
    # ------------------------------------------------------------------ #

    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Стримит СЫРЫЕ чанки сервера, включая служебные:
          {"type":"kernel","kernel_id":...} — id kernel'а (в т.ч. для 'new');
          {"type":"done"} — выполнение завершилось;
          {"type":"fatal","detail":...} — ошибка сервера/kernel'а.
        Плюс контрактные stdout/stderr/result/display_data/error/input_request.
        На input_request значение приходит через asend() и уходит серверу как
        input_reply.
        """
        url = self._ws_url(f"/v1/kernels/{kernel_id or 'new'}/execute")
        init = {"code": code, "allow_stdin": allow_stdin}
        if envs:
            init["envs"] = envs

        async with websockets.connect(
            url,
            additional_headers=self._headers,
            max_size=_WS_MAX_SIZE,
        ) as ws:
            await ws.send(json.dumps(init))
            async for raw in ws:
                chunk = json.loads(raw)
                if chunk.get("type") == "input_request":
                    reply = yield chunk
                    await ws.send(
                        json.dumps(
                            {
                                "type": "input_reply",
                                "value": "" if reply is None else str(reply),
                            }
                        )
                    )
                    continue
                yield chunk
                if chunk.get("type") in ("done", "fatal"):
                    return

    # ------------------------------------------------------------------ #
    # shell
    # ------------------------------------------------------------------ #

    async def run_shell(
        self,
        command: str,
        *,
        working_directory: str | None = None,
        block_until_ms: int = 30000,
        description: str | None = None,
        envs: dict[str, str] | None = None,
    ) -> ShellRunResult:
        payload = {
            "command": command,
            "working_directory": working_directory,
            "block_until_ms": block_until_ms,
            "description": description,
            "envs": envs,
        }
        data = await self._post_json("/v1/shell", payload)
        return ShellRunResult(**data)

    async def await_shell(
        self,
        shell_id: str,
        *,
        block_until_ms: int = 30000,
        pattern: str | None = None,
    ) -> ShellAwaitResult:
        payload = {"block_until_ms": block_until_ms, "pattern": pattern}
        data = await self._post_json(f"/v1/shell/{shell_id}/await", payload)
        return ShellAwaitResult(**data)

    async def list_shells(self, *, only_running: bool = False) -> list[dict[str, Any]]:
        async with self._session() as session:
            async with session.get(
                self._url("/v1/shell"),
                params={"only_running": str(only_running).lower()},
            ) as r:
                r.raise_for_status()
                data = await r.json()
        return data.get("shells", [])

    async def kill_shell(self, shell_id: str) -> dict[str, Any]:
        return await self._post_json(f"/v1/shell/{shell_id}/kill", None)

    # ------------------------------------------------------------------ #
    # files (non-persisted sandbox paths)
    # ------------------------------------------------------------------ #

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        session = self._session()
        try:
            resp = await session.get(
                self._url("/v1/files"), params={"path": sandbox_path}
            )
        except Exception:
            await session.close()
            raise
        if resp.status == 404:
            resp.release()
            await session.close()
            raise FileNotFoundError(f"File not found: {sandbox_path}")
        if resp.status >= 400:
            text = await resp.text()
            resp.release()
            await session.close()
            raise SandboxAPIError(f"read_file failed ({resp.status}): {text}")

        media_type = (
            resp.headers.get("Content-Type") or "application/octet-stream"
        ).split(";")[0]
        disposition = resp.headers.get("Content-Disposition", "")
        inline = disposition.startswith("inline")
        length_raw = resp.headers.get("Content-Length")
        content_length = (
            int(length_raw) if length_raw and length_raw.isdigit() else None
        )

        async def _iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.content.iter_chunked(_STREAM_CHUNK):
                    yield chunk
            finally:
                with contextlib.suppress(Exception):
                    resp.release()
                with contextlib.suppress(Exception):
                    await session.close()

        return StreamResult(
            stream=_iter(),
            media_type=media_type,
            inline=inline,
            content_length=content_length,
        )

    async def read_file_bytes(
        self, sandbox_path: str, *, max_bytes: int = _READ_BYTES_CAP
    ) -> bytes:
        """Собрать весь файл в память (для мелких служебных чтений, напр. meta).

        Ограничено max_bytes с ранним обрывом, чтобы служебное чтение не смогло
        затянуть в RAM гигабайты; при превышении — SandboxAPIError.
        """
        result = await self.read_file(sandbox_path)
        if isinstance(result, ContentResult):
            if len(result.data) > max_bytes:
                raise SandboxAPIError(
                    f"File exceeds read_file_bytes cap ({max_bytes} bytes)"
                )
            return result.data
        if isinstance(result, StreamResult):
            buf = bytearray()
            async for chunk in result.stream:
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise SandboxAPIError(
                        f"File exceeds read_file_bytes cap ({max_bytes} bytes)"
                    )
            return bytes(buf)
        raise SandboxAPIError("Unexpected read result type")

    async def write_file_content(self, sandbox_path: str, content: bytes) -> None:
        async with self._session() as session:
            async with session.put(
                self._url("/v1/files"), params={"path": sandbox_path}, data=content
            ) as r:
                if r.status >= 400:
                    text = await r.text()
                    raise SandboxAPIError(f"write_file failed ({r.status}): {text}")

    async def delete_file(self, sandbox_path: str, *, recursive: bool = False) -> None:
        async with self._session() as session:
            async with session.delete(
                self._url("/v1/files"),
                params={"path": sandbox_path, "recursive": str(recursive).lower()},
            ) as r:
                if r.status == 404:
                    return
                if r.status >= 400:
                    text = await r.text()
                    raise SandboxAPIError(f"delete_file failed ({r.status}): {text}")

    async def file_exists(self, sandbox_path: str) -> bool:
        async with self._session() as session:
            async with session.head(
                self._url("/v1/files"), params={"path": sandbox_path}
            ) as r:
                return r.status == 200

    # ------------------------------------------------------------------ #
    # internal
    # ------------------------------------------------------------------ #

    async def _post_json(
        self, path: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        async with self._session() as session:
            async with session.post(self._url(path), json=payload) as r:
                if r.status >= 400:
                    text = await r.text()
                    raise SandboxAPIError(f"POST {path} failed ({r.status}): {text}")
                return await r.json()
