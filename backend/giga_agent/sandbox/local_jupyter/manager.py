from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any

import aiohttp

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.core.process_supervisor import (
    ManagedProcessRecord,
    get_process_supervisor,
)
from giga_agent.sandbox.local_jupyter.dependencies import ensure_jupyter_dependencies

logger = get_logger(__name__)
_MANAGER: LocalJupyterServerManager | None = None
LOCAL_JUPYTER_KERNEL_NAME = "giga-agent-local-jupyter"
LOCAL_JUPYTER_KERNEL_DISPLAY_NAME = "Python (local_jupyter)"


@dataclass(slots=True)
class LocalJupyterHandle:
    pid: int
    port: int
    token: str
    base_url: str
    runtime_dir: str
    working_dir: str
    started_at: float


class LocalJupyterServerManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._handle: LocalJupyterHandle | None = None
        self._log_handle: IO[bytes] | None = None

    async def ensure_started(self) -> LocalJupyterHandle:
        async with self._lock:
            active = await self._get_active_handle()
            if active is not None:
                self._handle = active
                return active

            await self._cleanup_stale_state_unlocked()
            return await self._start_new_server()

    async def get_active_handle(self) -> LocalJupyterHandle | None:
        async with self._lock:
            return await self._get_active_handle()

    async def is_running(self) -> bool:
        return await self.get_active_handle() is not None

    async def cleanup_stale_state(self) -> None:
        async with self._lock:
            await self._cleanup_stale_state_unlocked()

    async def stop(self) -> None:
        async with self._lock:
            handle = await self._get_active_handle()
            if handle is None:
                await self._clear_state_unlocked()
                return
            await self._stop_handle_unlocked(handle)

    async def stop_pid(self, pid: int) -> None:
        async with self._lock:
            handle = await self._get_active_handle()
            metadata_handle = self._read_metadata_file()
            if handle is not None and handle.pid == pid:
                await self._stop_handle_unlocked(handle)
                return

            if not self._is_pid_alive(pid):
                self._unregister_supervised_process(pid)
                if (
                    (self._handle is not None and self._handle.pid == pid)
                    or (
                        metadata_handle is not None and metadata_handle.pid == pid
                    )
                ):
                    await self._clear_state_unlocked(pid=pid)
                return

            await self._terminate_pid_unlocked(pid)

            if (
                (self._handle is not None and self._handle.pid == pid)
                or (metadata_handle is not None and metadata_handle.pid == pid)
            ):
                await self._clear_state_unlocked(pid=pid)
            else:
                self._unregister_supervised_process(pid)

    async def _get_active_handle(self) -> LocalJupyterHandle | None:
        candidates: list[LocalJupyterHandle] = []
        if self._handle is not None:
            candidates.append(self._handle)

        metadata_handle = self._read_metadata_file()
        if metadata_handle is not None and (
            self._handle is None or metadata_handle.pid != self._handle.pid
        ):
            candidates.append(metadata_handle)

        for handle in candidates:
            pid_alive = self._is_pid_alive(handle.pid)
            if not pid_alive:
                continue
            probe_ok = await self._probe_server(handle.base_url, handle.token)
            if probe_ok:
                return handle

        return None

    async def _cleanup_stale_state_unlocked(self) -> None:
        metadata_handle = self._read_metadata_file()
        if metadata_handle is None:
            return
        if not self._is_pid_alive(metadata_handle.pid):
            await self._clear_state_unlocked(pid=metadata_handle.pid)
            return
        if await self._probe_server(metadata_handle.base_url, metadata_handle.token):
            self._handle = metadata_handle
            return
        await self._terminate_pid_unlocked(metadata_handle.pid)
        await self._clear_state_unlocked(pid=metadata_handle.pid)

    async def _start_new_server(self) -> LocalJupyterHandle:
        ensure_jupyter_dependencies()

        python_executable = self._python_executable()
        working_dir = self._working_dir()
        config_dir = self._config_dir()
        data_dir = self._data_dir()
        runtime_dir = self._runtime_dir()
        shims_dir = self._shims_dir()
        working_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        shims_dir.mkdir(parents=True, exist_ok=True)
        self._write_command_shims(
            shims_dir=shims_dir,
            python_executable=python_executable,
        )
        self._write_kernel_spec(
            data_dir=data_dir,
            shims_dir=shims_dir,
            python_executable=python_executable,
        )

        port = self._reserve_port()
        token = os.urandom(24).hex()
        base_url = f"http://127.0.0.1:{port}"
        command = [
            python_executable,
            "-m",
            "jupyter",
            "server",
            "--no-browser",
            "--allow-root",
            "--ip=127.0.0.1",
            f"--port={port}",
            f"--IdentityProvider.token={token}",
            f"--ServerApp.root_dir={working_dir}",
        ]
        env = self._jupyter_env(
            config_dir=config_dir,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
            shims_dir=shims_dir,
            python_executable=python_executable,
        )

        log_path = self._log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("ab")
        self._proc = subprocess.Popen(
            command,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        handle = LocalJupyterHandle(
            pid=self._proc.pid,
            port=port,
            token=token,
            base_url=base_url,
            runtime_dir=str(runtime_dir),
            working_dir=str(working_dir),
            started_at=time.time(),
        )

        try:
            await self._wait_until_ready(handle, timeout_sec=self._startup_timeout_sec())
        except Exception:
            await self.stop_pid(handle.pid)
            raise

        try:
            self._write_metadata_file(handle)
            self._register_supervised_process(handle)
        except Exception:
            await self.stop_pid(handle.pid)
            raise
        self._handle = handle
        return handle

    async def _wait_until_ready(
        self,
        handle: LocalJupyterHandle,
        *,
        timeout_sec: int,
    ) -> None:
        started_at = time.monotonic()
        while True:
            if await self._probe_server(handle.base_url, handle.token):
                return
            if not self._is_pid_alive(handle.pid):
                raise RuntimeError("Managed local Jupyter server exited before startup")
            if time.monotonic() - started_at >= timeout_sec:
                raise TimeoutError(
                    "Managed local Jupyter server did not become ready "
                    f"within {timeout_sec} seconds"
                )
            await asyncio.sleep(0.5)

    async def _probe_server(self, base_url: str, token: str) -> bool:
        headers = {"Authorization": f"token {token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=1.5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{base_url}/api/status",
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        return False
                    payload = await response.json()
                    return payload.get("started", False) is not False
        except Exception:
            return False

    async def _stop_handle_unlocked(self, handle: LocalJupyterHandle) -> None:
        await self._terminate_pid_unlocked(handle.pid)
        await self._clear_state_unlocked()

    async def _terminate_pid_unlocked(self, pid: int) -> None:
        graceful_timeout_sec = self._graceful_shutdown_timeout_sec()
        self._terminate_process_group(pid, force=False)
        graceful_exit = await self._wait_for_exit(pid, graceful_timeout_sec)
        if not graceful_exit:
            self._terminate_process_group(pid, force=True)
            await self._wait_for_exit(pid, 1.0)

    async def _clear_state_unlocked(self, *, pid: int | None = None) -> None:
        cleanup_pid = pid
        if cleanup_pid is None and self._handle is not None:
            cleanup_pid = self._handle.pid
        self._handle = None
        self._proc = None
        self._remove_metadata_file()
        if cleanup_pid is not None:
            self._unregister_supervised_process(cleanup_pid)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    async def _wait_for_exit(self, pid: int, timeout_sec: float) -> bool:
        started_at = time.monotonic()
        while time.monotonic() - started_at < timeout_sec:
            if not self._is_pid_alive(pid):
                return True
            await asyncio.sleep(0.2)
        return not self._is_pid_alive(pid)

    def _metadata_path(self) -> Path:
        return ensure_giga_agent_dir() / "local_jupyter" / "server.json"

    def _log_path(self) -> Path:
        return ensure_giga_agent_dir() / "local_jupyter" / "server.log"

    def _register_supervised_process(self, handle: LocalJupyterHandle) -> None:
        pgid = self._process_group_id(handle.pid)
        get_process_supervisor().register_process(
            ManagedProcessRecord(
                kind="local_jupyter",
                pid=handle.pid,
                pgid=pgid,
                graceful_timeout_sec=float(self._graceful_shutdown_timeout_sec()),
                metadata={
                    "base_url": handle.base_url,
                    "runtime_dir": handle.runtime_dir,
                    "working_dir": handle.working_dir,
                },
            )
        )

    def _unregister_supervised_process(self, pid: int) -> None:
        get_process_supervisor().unregister_process(kind="local_jupyter", pid=pid)

    def _working_dir(self) -> Path:
        settings = get_settings()
        raw = settings.giga_agent_local_jupyter_working_dir
        if raw:
            return Path(raw).expanduser().resolve()
        return (ensure_giga_agent_dir() / "local_jupyter" / "workspace").resolve()

    def _runtime_dir(self) -> Path:
        settings = get_settings()
        raw = settings.giga_agent_local_jupyter_runtime_dir
        if raw:
            return Path(raw).expanduser().resolve()
        return (ensure_giga_agent_dir() / "local_jupyter" / "runtime").resolve()

    def _config_dir(self) -> Path:
        return (ensure_giga_agent_dir() / "local_jupyter" / "config").resolve()

    def _data_dir(self) -> Path:
        return (ensure_giga_agent_dir() / "local_jupyter" / "data").resolve()

    def _shims_dir(self) -> Path:
        return (ensure_giga_agent_dir() / "local_jupyter" / "shims").resolve()

    def _kernel_spec_dir(self, *, data_dir: Path) -> Path:
        return (data_dir / "kernels" / LOCAL_JUPYTER_KERNEL_NAME).resolve()

    def _python_bin_dir(self, *, python_executable: str) -> Path:
        return Path(python_executable).expanduser().resolve().parent

    def _virtual_env_dir(self, *, python_executable: str) -> Path | None:
        python_bin_dir = self._python_bin_dir(python_executable=python_executable)
        if python_bin_dir.name.lower() in {"bin", "scripts"}:
            return python_bin_dir.parent.resolve()
        return None

    def _runtime_command_env(
        self,
        *,
        shims_dir: Path,
        python_executable: str,
    ) -> dict[str, str]:
        env = os.environ.copy()
        python_bin_dir = self._python_bin_dir(python_executable=python_executable)
        path_entries = [str(shims_dir), str(python_bin_dir)]
        existing_path = env.get("PATH")
        if existing_path:
            path_entries.append(existing_path)
        env["PATH"] = os.pathsep.join(path_entries)
        venv_dir = self._virtual_env_dir(python_executable=python_executable)
        if venv_dir is not None:
            env["VIRTUAL_ENV"] = str(venv_dir)
        env["PYTHONNOUSERSITE"] = "1"
        env["PIP_REQUIRE_VIRTUALENV"] = "1"
        return env

    def _jupyter_env(
        self,
        *,
        config_dir: Path,
        data_dir: Path,
        runtime_dir: Path,
        shims_dir: Path,
        python_executable: str,
    ) -> dict[str, str]:
        env = self._runtime_command_env(
            shims_dir=shims_dir,
            python_executable=python_executable,
        )
        # Run Jupyter with isolated config/runtime paths so global user or system
        # extensions do not affect local sandbox startup.
        env["JUPYTER_NO_CONFIG"] = "1"
        env["JUPYTER_CONFIG_DIR"] = str(config_dir)
        env["JUPYTER_DATA_DIR"] = str(data_dir)
        env["JUPYTER_RUNTIME_DIR"] = str(runtime_dir)
        return env

    def _kernel_env(
        self,
        *,
        shims_dir: Path,
        python_executable: str,
    ) -> dict[str, str]:
        return self._runtime_command_env(
            shims_dir=shims_dir,
            python_executable=python_executable,
        )

    def _write_command_shims(
        self,
        *,
        shims_dir: Path,
        python_executable: str,
    ) -> None:
        shims_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            shim_targets = {
                "python.cmd": f'@"{python_executable}" %*\r\n',
                "python3.cmd": f'@"{python_executable}" %*\r\n',
                "pip.cmd": f'@"{python_executable}" -m pip %*\r\n',
                "pip3.cmd": f'@"{python_executable}" -m pip %*\r\n',
            }
        else:
            shim_targets = {
                "python": f'#!/bin/sh\nexec "{python_executable}" "$@"\n',
                "python3": f'#!/bin/sh\nexec "{python_executable}" "$@"\n',
                "pip": f'#!/bin/sh\nexec "{python_executable}" -m pip "$@"\n',
                "pip3": f'#!/bin/sh\nexec "{python_executable}" -m pip "$@"\n',
            }

        for name, content in shim_targets.items():
            path = shims_dir / name
            path.write_text(content, encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o755)

    def _write_kernel_spec(
        self,
        *,
        data_dir: Path,
        shims_dir: Path,
        python_executable: str,
    ) -> None:
        kernel_spec_dir = self._kernel_spec_dir(data_dir=data_dir)
        kernel_spec_dir.mkdir(parents=True, exist_ok=True)
        kernel_spec = {
            "argv": [
                python_executable,
                "-m",
                "ipykernel_launcher",
                "-f",
                "{connection_file}",
            ],
            "display_name": LOCAL_JUPYTER_KERNEL_DISPLAY_NAME,
            "language": "python",
            "env": self._kernel_env(
                shims_dir=shims_dir,
                python_executable=python_executable,
            ),
            "metadata": {
                "debugger": True,
            },
        }
        (kernel_spec_dir / "kernel.json").write_text(
            json.dumps(kernel_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _python_executable(self) -> str:
        configured = (get_settings().giga_agent_local_jupyter_python_executable or "").strip()
        return configured or sys.executable

    def _startup_timeout_sec(self) -> int:
        return get_settings().giga_agent_local_jupyter_startup_timeout_sec

    def _graceful_shutdown_timeout_sec(self) -> int:
        return get_settings().giga_agent_local_jupyter_graceful_shutdown_timeout_sec

    def _reserve_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    def _write_metadata_file(self, handle: LocalJupyterHandle) -> None:
        path = self._metadata_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(handle)), encoding="utf-8")

    def _read_metadata_file(self) -> LocalJupyterHandle | None:
        path = self._metadata_path()
        if not path.is_file():
            return None
        try:
            raw_data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._remove_metadata_file()
            return None

        try:
            return LocalJupyterHandle(
                pid=int(raw_data["pid"]),
                port=int(raw_data["port"]),
                token=str(raw_data["token"]),
                base_url=str(raw_data["base_url"]),
                runtime_dir=str(raw_data["runtime_dir"]),
                working_dir=str(raw_data["working_dir"]),
                started_at=float(raw_data["started_at"]),
            )
        except (KeyError, TypeError, ValueError):
            self._remove_metadata_file()
            return None

    def _remove_metadata_file(self) -> None:
        try:
            self._metadata_path().unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove local Jupyter metadata file")

    def _is_pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _process_group_id(self, pid: int) -> int | None:
        if pid <= 0:
            return None
        if os.name == "nt":
            return pid
        try:
            return int(os.getpgid(pid))
        except OSError:
            return None

    def _terminate_process_group(self, pid: int, *, force: bool) -> None:
        if not self._is_pid_alive(pid):
            return
        if os.name == "nt":
            sig = signal.SIGTERM if not force else signal.SIGKILL
            try:
                os.kill(pid, sig)
            except OSError:
                return
            return

        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            process_group_id = int(os.getpgid(pid))
            os.killpg(process_group_id, sig)
        except OSError:
            return


def get_local_jupyter_server_manager() -> LocalJupyterServerManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LocalJupyterServerManager()
    return _MANAGER
