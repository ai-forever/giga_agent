"""Native kernel management via jupyter_client.

Переиспользуем kernelspec'ы, уже установленные в образе (``python3``, ``bash``),
но управляем kernel'ами сами — без второго Jupyter HTTP-сервера и без токен-
жонглирования. Это даёт чистый собственный API: create / list / interrupt /
restart / delete + стриминг выполнения с двунаправленным stdin.

Стриминг мапится в те же dict-чанки, что и
giga_agent.sandbox.jupyter.JupyterSandbox.run_code, чтобы тонкий клиент почти
не менялся.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from queue import Empty
from typing import Any

from jupyter_client.multikernelmanager import AsyncMultiKernelManager

from .config import Settings, get_settings


def inject_env_prelude(code: str, envs: dict[str, str] | None) -> str:
    """Портирование giga_agent.sandbox.jupyter._inject_env_prelude."""
    if not envs:
        return code
    managed = {str(k): str(v) for k, v in envs.items()}
    envs_json = json.dumps(managed, ensure_ascii=False)
    prelude = "\n".join(
        [
            "import json as _sbx_json",
            "import os as _sbx_os",
            f"_sbx_envs = _sbx_json.loads({envs_json!r})",
            "for _sbx_k, _sbx_v in _sbx_envs.items():",
            "    _sbx_os.environ[_sbx_k] = _sbx_v",
            "del _sbx_k, _sbx_v, _sbx_envs, _sbx_json, _sbx_os",
            "",
        ]
    )
    return prelude + code


@dataclass(slots=True)
class KernelEntry:
    kernel_id: str
    kernel_name: str
    cwd: str | None
    client: Any  # AsyncKernelClient
    last_activity_at: float = field(default_factory=time.time)
    execution_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class KernelPool:
    """Пул kernel'ов поверх AsyncMultiKernelManager с LRU-эвикцией."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._mkm = AsyncMultiKernelManager()
        self._entries: OrderedDict[str, KernelEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def create(
        self,
        *,
        kernel_name: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> KernelEntry:
        name = kernel_name or self._settings.default_kernel_name
        cwd = cwd or self._settings.workdir
        start_kwargs: dict[str, Any] = {"kernel_name": name, "cwd": cwd}
        if env:
            start_kwargs["env"] = {str(k): str(v) for k, v in env.items()}

        async with self._lock:
            await self._enforce_limit_locked()
            kernel_id = await self._mkm.start_kernel(**start_kwargs)
            km = self._mkm.get_kernel(kernel_id)
            client = km.client()
            client.start_channels()
            try:
                await client.wait_for_ready(
                    timeout=self._settings.kernel_startup_timeout_sec
                )
            except Exception:
                client.stop_channels()
                await self._mkm.shutdown_kernel(kernel_id, now=True)
                raise
            entry = KernelEntry(
                kernel_id=kernel_id, kernel_name=name, cwd=cwd, client=client
            )
            self._entries[kernel_id] = entry
            self._entries.move_to_end(kernel_id)
            return entry

    async def get_or_create(
        self, kernel_id: str | None, **create_kwargs: Any
    ) -> KernelEntry:
        if kernel_id:
            async with self._lock:
                entry = self._entries.get(kernel_id)
                if entry is not None and self._safe_get_km(kernel_id) is not None:
                    self._entries.move_to_end(kernel_id)
                    entry.last_activity_at = time.time()
                    return entry
        return await self.create(**create_kwargs)

    def list(self) -> list[KernelEntry]:
        return list(self._entries.values())

    async def interrupt(self, kernel_id: str) -> bool:
        km = self._safe_get_km(kernel_id)
        if km is None:
            return False
        await km.interrupt_kernel()
        return True

    async def restart(self, kernel_id: str) -> bool:
        entry = self._entries.get(kernel_id)
        km = self._safe_get_km(kernel_id)
        if km is None or entry is None:
            return False
        # под entry.lock: не подменяем client, пока in-flight execute читает из него
        async with entry.lock:
            await km.restart_kernel(now=False)
            try:
                entry.client.stop_channels()
            except Exception:
                pass
            entry.client = km.client()
            entry.client.start_channels()
            await entry.client.wait_for_ready(
                timeout=self._settings.kernel_startup_timeout_sec
            )
            entry.execution_count = 0
            entry.last_activity_at = time.time()
        return True

    async def delete(self, kernel_id: str) -> bool:
        async with self._lock:
            entry = self._entries.pop(kernel_id, None)
        if entry is None:
            if self._safe_get_km(kernel_id) is None:
                return False
            await self._mkm.shutdown_kernel(kernel_id, now=True)
            return True
        # прерываем текущее выполнение, чтобы execute быстро отпустил entry.lock,
        # затем под локом рвём каналы и глушим kernel (без гонки с execute)
        km = self._safe_get_km(kernel_id)
        if km is not None:
            try:
                await km.interrupt_kernel()
            except Exception:
                pass
        async with entry.lock:
            try:
                entry.client.stop_channels()
            except Exception:
                pass
            if self._safe_get_km(kernel_id) is not None:
                await self._mkm.shutdown_kernel(kernel_id, now=True)
        return True

    async def shutdown_all(self) -> None:
        for entry in list(self._entries.values()):
            try:
                entry.client.stop_channels()
            except Exception:
                pass
        self._entries.clear()
        try:
            await self._mkm.shutdown_all(now=True)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # execution
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        entry: KernelEntry,
        code: str,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], str]:
        """Выполнить код, стримя чанки. Значение из ``asend()`` уходит как
        ответ на ``input_request`` (интерактивный stdin)."""
        code = inject_env_prelude(code, envs)
        # take-over: новый запрос вытесняет текущее выполнение на этом kernel'е
        # (kernel исполняет код последовательно; «запусти снова» = стоп-и-замени).
        if entry.lock.locked():
            await self._preempt(entry)
        await entry.lock.acquire()
        try:
            client = entry.client
            entry.last_activity_at = time.time()
            msg_id = client.execute(code, allow_stdin=allow_stdin, stop_on_error=True)
            while True:
                handled = False

                # 1) iopub — основной поток вывода
                try:
                    msg = await client.get_iopub_msg(timeout=0.02)
                    handled = True
                except (Empty, asyncio.TimeoutError):
                    msg = None
                except Exception as exc:  # канал умер
                    yield {"type": "fatal", "detail": f"iopub channel error: {exc}"}
                    return

                if msg is not None:
                    if msg.get("parent_header", {}).get("msg_id") != msg_id:
                        pass
                    else:
                        chunk, done = _map_iopub(msg, entry)
                        if chunk is not None:
                            yield chunk
                        if done:
                            entry.last_activity_at = time.time()
                            yield {"type": "done"}
                            return

                # 2) stdin — запросы input()
                if allow_stdin:
                    try:
                        stdin_msg = await client.get_stdin_msg(timeout=0.001)
                    except (Empty, asyncio.TimeoutError):
                        stdin_msg = None
                    except Exception:
                        stdin_msg = None
                    if stdin_msg is not None and (
                        stdin_msg.get("msg_type") == "input_request"
                    ):
                        content = stdin_msg.get("content", {})
                        reply = yield {
                            "type": "input_request",
                            "prompt": content.get("prompt", ""),
                            "password": content.get("password", False),
                        }
                        client.input("" if reply is None else str(reply))
                        handled = True

                if not handled:
                    await asyncio.sleep(0)
        finally:
            entry.lock.release()

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #

    async def _preempt(self, entry: KernelEntry) -> None:
        """Вытеснить текущее выполнение на ``entry``, чтобы новый запрос занял
        kernel сразу. Мягко (SIGINT); если за ``preempt_timeout_sec`` лок не
        освободился (SIGINT не берёт C-циклы/блокирующий I/O) — жёстко рестартим
        процесс kernel'а и пересобираем client. По выходу: лок свободен,
        ``entry.client`` жив и готов к работе."""
        km = self._safe_get_km(entry.kernel_id)
        if km is None:
            return
        # 1) мягко: SIGINT -> KeyboardInterrupt в ячейке -> execute сам завершится
        try:
            await km.interrupt_kernel()
        except Exception:
            pass
        if await self._wait_lock_free(entry, self._settings.preempt_timeout_sec):
            return  # client цел, состояние kernel'а сохранено
        # 2) жёстко: рестарт процесса рвёт каналы -> текущий execute уходит в
        #    fatal и отпускает лок; после этого пересобираем client (состояние
        #    kernel'а при этом теряется — осознанный компромисс)
        try:
            await km.restart_kernel(now=True)
        except Exception:
            pass
        await self._wait_lock_free(entry, self._settings.kernel_startup_timeout_sec)
        async with entry.lock:
            try:
                entry.client.stop_channels()
            except Exception:
                pass
            entry.client = km.client()
            entry.client.start_channels()
            await entry.client.wait_for_ready(
                timeout=self._settings.kernel_startup_timeout_sec
            )
            entry.execution_count = 0
            entry.last_activity_at = time.time()

    @staticmethod
    async def _wait_lock_free(entry: KernelEntry, timeout: float) -> bool:
        """Дождаться освобождения ``entry.lock`` (текущий execute завершится и
        отпустит его). True — освободился в срок, False — таймаут."""
        deadline = time.monotonic() + max(timeout, 0.0)
        while entry.lock.locked():
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    def _safe_get_km(self, kernel_id: str) -> Any:
        try:
            return self._mkm.get_kernel(kernel_id)
        except KeyError:
            return None

    async def _enforce_limit_locked(self) -> None:
        if not self._settings.kernel_lru_enabled:
            return
        while len(self._entries) >= self._settings.max_kernels:
            evict_id, entry = next(iter(self._entries.items()))
            self._entries.pop(evict_id, None)
            try:
                entry.client.stop_channels()
            except Exception:
                pass
            try:
                await self._mkm.shutdown_kernel(evict_id, now=True)
            except Exception:
                pass


def _map_iopub(
    msg: dict[str, Any], entry: KernelEntry
) -> tuple[dict[str, Any] | None, bool]:
    """Смапить iopub-сообщение в чанк run_code. Возвращает (chunk, is_done)."""
    msg_type = msg.get("msg_type")
    content = msg.get("content", {})

    if msg_type == "stream":
        return {
            "type": content.get("name", "stdout"),
            "text": content.get("text", ""),
        }, False
    if msg_type == "execute_result":
        entry.execution_count = content.get("execution_count", entry.execution_count)
        return {
            "type": "result",
            "data": content.get("data", {}),
            "execution_count": content.get("execution_count"),
        }, False
    if msg_type == "display_data":
        return {"type": "display_data", "data": content.get("data", {})}, False
    if msg_type == "error":
        return {
            "type": "error",
            "ename": content.get("ename", ""),
            "evalue": content.get("evalue", ""),
            "traceback": content.get("traceback", []),
        }, False
    if msg_type == "status" and content.get("execution_state") == "idle":
        return None, True
    return None, False
