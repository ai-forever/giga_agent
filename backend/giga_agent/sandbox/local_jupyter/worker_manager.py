"""Parent-side lifecycle and protocol bridge for local Python workers."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from giga_agent.conf import get_settings
from giga_agent.core.process_supervisor import (
    ManagedProcessRecord,
    get_process_supervisor,
)
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.sandbox.secure_exec.launch import (
    SecureProcessConfig,
    launch_secure_process,
)
from giga_agent.sandbox.secure_exec.policy import SandboxAccessPolicy
from giga_agent.sandbox.local_python_environment import LocalPythonEnvironment

_WORKER_KIND = "local_python_worker"
_GRACEFUL_STOP_TIMEOUT_SEC = 2.0


class PythonWorkerError(RuntimeError):
    """The worker exited or violated its line-delimited JSON contract."""


@dataclass(slots=True)
class _Worker:
    process: subprocess.Popen[bytes]


class LocalPythonWorkerManager:
    """Keep exactly one persistent child process for every graph kernel id."""

    def __init__(self) -> None:
        self._workers: dict[str, _Worker] = {}
        self._kernel_locks: dict[str, asyncio.Lock] = {}
        self._manager_lock: asyncio.Lock | None = None

    def _lock(self) -> asyncio.Lock:
        if self._manager_lock is None:
            self._manager_lock = asyncio.Lock()
        return self._manager_lock

    def python_environment(self) -> LocalPythonEnvironment:
        return LocalPythonEnvironment(
            python_executable=sys.executable,
            shims_dir=ensure_giga_agent_dir() / "local_python" / "worker_shims",
        )

    def get_shell_env(
        self,
        *,
        extra_envs: dict[str, str] | None = None,
    ) -> dict[str, str]:
        return self.python_environment().shell_env(extra_envs=extra_envs)

    def _kernel_lock(self, kernel_id: str) -> asyncio.Lock:
        lock = self._kernel_locks.get(kernel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._kernel_locks[kernel_id] = lock
        return lock

    async def run_code(
        self,
        *,
        kernel_id: str,
        code: str,
        envs: dict[str, str] | None,
        cwd: Path,
        safe_execution: bool,
        policy: SandboxAccessPolicy | None,
    ) -> AsyncGenerator[dict[str, Any], str]:
        completed = False
        worker: _Worker | None = None
        try:
            async with self._kernel_lock(kernel_id):
                worker = await self._get_or_start(
                    kernel_id=kernel_id,
                    cwd=cwd,
                    safe_execution=safe_execution,
                    policy=policy,
                )
                request_id = uuid.uuid4().hex
                await self._write_message(
                    worker.process,
                    {
                        "type": "execute",
                        "request_id": request_id,
                        "code": code,
                        "envs": envs or {},
                    },
                )

                while True:
                    event = await self._read_message(worker.process)
                    if event.get("request_id") != request_id:
                        raise PythonWorkerError("Received an event for another request")
                    event_type = event.get("type")
                    if event_type == "done":
                        completed = True
                        return
                    if event_type == "input_request":
                        reply = yield {
                            "type": "input_request",
                            "prompt": str(event.get("prompt", "")),
                            "password": bool(event.get("password", False)),
                        }
                        await self._write_message(
                            worker.process,
                            {
                                "type": "input_reply",
                                "request_id": request_id,
                                "value": "" if reply is None else str(reply),
                            },
                        )
                        continue
                    if event_type not in {
                        "stdout",
                        "stderr",
                        "result",
                        "display_data",
                        "error",
                    }:
                        raise PythonWorkerError(
                            f"Unsupported Python worker event: {event_type!r}"
                        )
                    event.pop("request_id", None)
                    yield event
        except asyncio.CancelledError:
            raise
        except PythonWorkerError as exc:
            yield {
                "type": "error",
                "ename": exc.__class__.__name__,
                "evalue": str(exc),
                "traceback": [],
            }
        finally:
            if not completed and worker is not None:
                await self._discard_worker(kernel_id, worker)

    async def stop_kernel(self, kernel_id: str | None) -> None:
        if not kernel_id:
            return
        async with self._kernel_lock(kernel_id):
            worker = self._workers.get(kernel_id)
            if worker is not None:
                await self._discard_worker(kernel_id, worker)

    async def stop_all(self) -> None:
        async with self._lock():
            workers = list(self._workers.items())
        for kernel_id, worker in workers:
            await self.stop_kernel(kernel_id)

    async def _get_or_start(
        self,
        *,
        kernel_id: str,
        cwd: Path,
        safe_execution: bool,
        policy: SandboxAccessPolicy | None,
    ) -> _Worker:
        async with self._lock():
            worker = self._workers.get(kernel_id)
            if worker is not None and worker.process.poll() is None:
                return worker
            if worker is not None:
                self._workers.pop(kernel_id, None)
                await self._stop_process(worker.process)
            process = self._start_process(
                kernel_id=kernel_id,
                cwd=cwd,
                safe_execution=safe_execution,
                policy=policy,
            )
            worker = _Worker(process=process)
            self._workers[kernel_id] = worker
            return worker

    def _start_process(
        self,
        *,
        kernel_id: str,
        cwd: Path,
        safe_execution: bool,
        policy: SandboxAccessPolicy | None,
    ) -> subprocess.Popen[bytes]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "giga_agent.sandbox.local_jupyter.python_worker",
        ]
        env = os.environ.copy()
        env.setdefault("MPLBACKEND", "Agg")
        if safe_execution:
            if policy is None:
                raise PythonWorkerError("Missing sandbox policy for secure worker")
            policy.assert_valid_cwd(require_writable=True)
            launch = launch_secure_process(
                SecureProcessConfig(
                    command=command,
                    policy=policy,
                    backend=get_settings().giga_agent_local_jupyter_secure_exec_backend,  # type: ignore[arg-type]
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            )
            process = launch.process
        else:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        self._register_process(process, kernel_id)
        return process

    async def _discard_worker(self, kernel_id: str, worker: _Worker) -> None:
        async with self._lock():
            if self._workers.get(kernel_id) is worker:
                self._workers.pop(kernel_id, None)
        await self._stop_process(worker.process)

    async def _write_message(
        self, process: subprocess.Popen[bytes], message: dict[str, Any]
    ) -> None:
        if process.poll() is not None or process.stdin is None:
            raise PythonWorkerError("Python worker exited before receiving a command")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

        def write() -> None:
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.flush()

        try:
            await asyncio.to_thread(write)
        except (BrokenPipeError, OSError) as exc:
            raise PythonWorkerError(
                "Python worker control stream is unavailable"
            ) from exc

    async def _read_message(self, process: subprocess.Popen[bytes]) -> dict[str, Any]:
        if process.stdout is None:
            raise PythonWorkerError("Python worker stdout is unavailable")
        line = await asyncio.to_thread(process.stdout.readline)
        if not line:
            raise PythonWorkerError(
                f"Python worker exited unexpectedly (code {process.poll()!r})"
            )
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PythonWorkerError("Python worker emitted invalid JSON") from exc
        if not isinstance(message, dict):
            raise PythonWorkerError("Python worker emitted a non-object event")
        return message

    async def _stop_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            self._unregister_process(process.pid)
            return
        try:
            await self._write_message(process, {"type": "shutdown"})
        except PythonWorkerError:
            pass
        try:
            await asyncio.to_thread(process.wait, _GRACEFUL_STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            self._terminate_process_group(process, force=False)
            try:
                await asyncio.to_thread(process.wait, _GRACEFUL_STOP_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process, force=True)
                await asyncio.to_thread(process.wait)
        finally:
            self._unregister_process(process.pid)

    @staticmethod
    def _terminate_process_group(
        process: subprocess.Popen[bytes], *, force: bool
    ) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            if force:
                process.kill()
            else:
                process.terminate()
            return
        import signal

        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass

    @staticmethod
    def _register_process(process: subprocess.Popen[bytes], kernel_id: str) -> None:
        get_process_supervisor().register_process(
            ManagedProcessRecord(
                kind=_WORKER_KIND,
                pid=process.pid,
                pgid=None if os.name == "nt" else process.pid,
                graceful_timeout_sec=_GRACEFUL_STOP_TIMEOUT_SEC,
                metadata={"kernel_id": kernel_id},
            )
        )

    @staticmethod
    def _unregister_process(pid: int) -> None:
        get_process_supervisor().unregister_process(kind=_WORKER_KIND, pid=pid)


_MANAGER: LocalPythonWorkerManager | None = None


def get_local_python_worker_manager() -> LocalPythonWorkerManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LocalPythonWorkerManager()
    return _MANAGER
