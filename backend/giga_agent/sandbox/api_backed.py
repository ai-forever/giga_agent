"""APIBackedSandbox — базовый класс для песочниц поверх SandboxAPI Server.

Наследуют его провайдеры, у которых песочница РАЗВЁРНУТА УДАЛЁННО и внутри неё
крутится in-guest SandboxAPI Server: local_docker, e2b. Такой провайдер
делегирует серверу:
  * run_code (через self._api_run_code, вызывается из subclass.run_code);
  * run_shell / await_shell (переопределены здесь с fallback на super());
  * файловые операции над НЕ-persisted путями песочницы
    (self._api_read_file / _api_write_file / _api_delete_file / _api_file_exists).

Persisted-хранилище (S3 у e2b, host-FS у local_docker) и скиллы остаются на
стороне провайдера и сюда НЕ делегируются.

local_jupyter НЕ наследует этот класс: он исполняется локально на машине
пользователя, сервер ему не нужен.

Делегирование включается только когда проставлены api_base_url и api_token
(их выставляет lifecycle при старте песочницы, как base_url/jupyter_token).
Пока они пустые — поведение полностью legacy (super()).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any, ClassVar

from giga_agent.sandbox.base import BaseSandbox, FileReadResult
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellRunResult
from giga_agent.sandbox.sandbox_api.client import SandboxAPIClient, SandboxAPIError


class APIBackedSandbox(BaseSandbox):
    api_base_url: str | None = None
    api_token: str | None = None

    _runtime_fields: ClassVar[set[str]] = BaseSandbox._runtime_fields | {
        "api_base_url",
        "api_token",
    }

    # ------------------------------------------------------------------ #
    # gate / client
    # ------------------------------------------------------------------ #

    def _sandbox_api_enabled(self) -> bool:
        return bool(self.api_base_url and self.api_token)

    def _sandbox_api_client(self) -> SandboxAPIClient:
        if not self._sandbox_api_enabled():
            raise SandboxAPIError(
                "SandboxAPI is not configured (api_base_url/api_token)"
            )
        return SandboxAPIClient(self.api_base_url, self.api_token)  # type: ignore[arg-type]

    async def _wait_for_sandbox_api(self, timeout_sec: float) -> bool:
        """Ждать готовности in-guest SandboxAPI Server (/healthz). Возвращает
        True, если сервер поднялся за отведённое время."""
        client = SandboxAPIClient(self.api_base_url or "", self.api_token or "")
        deadline = time.monotonic() + max(timeout_sec, 1.0)
        while time.monotonic() < deadline:
            if await client.is_up():
                return True
            await asyncio.sleep(0.5)
        return await client.is_up()

    # ------------------------------------------------------------------ #
    # shell (gate + super-fallback)
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
        return await self._sandbox_api_client().run_shell(
            command,
            working_directory=working_directory,
            block_until_ms=block_until_ms,
            description=description,
            envs=envs,
        )

    async def await_shell(
        self,
        shell_id: str,
        *,
        block_until_ms: int = 30000,
        pattern: str | None = None,
    ) -> ShellAwaitResult:
        return await self._sandbox_api_client().await_shell(
            shell_id, block_until_ms=block_until_ms, pattern=pattern
        )

    # ------------------------------------------------------------------ #
    # run_code (общий для всех API-backed провайдеров)
    # ------------------------------------------------------------------ #

    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        del kwargs
        gen = self._api_run_code(
            code, kernel_id=kernel_id, allow_stdin=allow_stdin, envs=envs
        )
        pending: str | None = None
        while True:
            try:
                chunk = await (
                    gen.asend(pending) if pending is not None else anext(gen)
                )
            except StopAsyncIteration:
                break
            pending = yield chunk

    # ------------------------------------------------------------------ #
    # run_code (вызывается из subclass.run_code под gate'ом)
    # ------------------------------------------------------------------ #

    async def _api_run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], str]:
        """Стримит контрактные чанки run_code через SandboxAPI Server.

        Служебные чанки сервера обрабатываются локально:
          kernel -> сохраняем self._kernel_id; done -> завершаем; fatal -> raise.
        Значение из asend() (ответ на input_request) прокидывается в клиент.
        """
        client = self._sandbox_api_client()
        gen = client.run_code(
            code, kernel_id=kernel_id, allow_stdin=allow_stdin, envs=envs
        )
        pending: str | None = None
        try:
            while True:
                try:
                    chunk = await (
                        gen.asend(pending) if pending is not None else anext(gen)
                    )
                except StopAsyncIteration:
                    break
                pending = None
                ctype = chunk.get("type")
                if ctype == "kernel":
                    kid = chunk.get("kernel_id")
                    if kid:
                        # _kernel_id объявлен в JupyterSandbox (PrivateAttr)
                        self._kernel_id = kid
                    continue
                if ctype == "done":
                    break
                if ctype == "fatal":
                    raise SandboxAPIError(
                        chunk.get("detail") or "kernel execution failed"
                    )
                pending = yield chunk
        finally:
            await gen.aclose()

    # ------------------------------------------------------------------ #
    # files (НЕ-persisted пути; persisted-ветку держит провайдер)
    # ------------------------------------------------------------------ #

    async def _api_read_file(self, sandbox_path: str) -> FileReadResult:
        return await self._sandbox_api_client().read_file(sandbox_path)

    async def _api_write_file(self, sandbox_path: str, content: bytes) -> None:
        await self._sandbox_api_client().write_file_content(sandbox_path, content)

    async def _api_delete_file(self, sandbox_path: str) -> None:
        await self._sandbox_api_client().delete_file(sandbox_path)

    async def _api_file_exists(self, sandbox_path: str) -> bool:
        return await self._sandbox_api_client().file_exists(sandbox_path)
