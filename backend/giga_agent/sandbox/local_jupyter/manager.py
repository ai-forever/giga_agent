from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections import OrderedDict
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
from giga_agent.sandbox.local_python_environment import LocalPythonEnvironment
from giga_agent.sandbox.secure_exec import (
    SandboxAccessPolicy,
    SecureProcessConfig,
    launch_secure_process,
)

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
    secure_execution: bool = False
    secure_exec_backend: str | None = None
    policy_fingerprint: str | None = None


class LocalJupyterServerManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._handle: LocalJupyterHandle | None = None
        self._log_handle: IO[bytes] | None = None
        # owner_id -> ordered {kernel_id: None}; insertion order is LRU order
        # (oldest first). Touched on every create/reuse via note_kernel_use.
        self._owner_kernels: dict[str, OrderedDict[str, None]] = {}
        self._kernel_lock = asyncio.Lock()

    async def ensure_started(
        self,
        *,
        safe_execution: bool = False,
        policy: SandboxAccessPolicy | None = None,
        secure_exec_backend: str = "auto",
    ) -> LocalJupyterHandle:
        async with self._lock:
            active = await self._get_active_handle()
            if active is not None:
                if self._handle_matches_request(
                    active,
                    safe_execution=safe_execution,
                    policy=policy,
                ):
                    self._handle = active
                    return active
                await self._stop_handle_unlocked(active)

            await self._cleanup_stale_state_unlocked()
            return await self._start_new_server(
                safe_execution=safe_execution,
                policy=policy,
                secure_exec_backend=secure_exec_backend,
            )

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
                if (self._handle is not None and self._handle.pid == pid) or (
                    metadata_handle is not None and metadata_handle.pid == pid
                ):
                    await self._clear_state_unlocked(pid=pid)
                return

            await self._terminate_pid_unlocked(pid)

            if (self._handle is not None and self._handle.pid == pid) or (
                metadata_handle is not None and metadata_handle.pid == pid
            ):
                await self._clear_state_unlocked(pid=pid)
            else:
                self._unregister_supervised_process(pid)

    def note_kernel_use(self, owner_id: Any, kernel_id: str) -> None:
        """Record that ``kernel_id`` belongs to ``owner_id`` and mark it as the
        most-recently-used kernel of that owner."""
        if owner_id is None or not kernel_id:
            return
        key = str(owner_id)
        kernels = self._owner_kernels.setdefault(key, OrderedDict())
        kernels[kernel_id] = None
        kernels.move_to_end(kernel_id)

    async def enforce_kernel_limit(
        self,
        *,
        owner_id: Any,
        limit: int,
        base_url: str,
        token: str,
    ) -> None:
        """Evict least-recently-used kernels of ``owner_id`` until creating one
        more would stay within ``limit``. No-op when ``limit`` <= 0."""
        if owner_id is None or limit <= 0:
            return
        key = str(owner_id)
        async with self._kernel_lock:
            kernels = self._owner_kernels.get(key)
            if not kernels:
                return
            while len(kernels) >= limit:
                evicted_id, _ = next(iter(kernels.items()))
                kernels.pop(evicted_id, None)
                await self._delete_kernel(base_url, token, evicted_id)
            if not kernels:
                self._owner_kernels.pop(key, None)

    async def _delete_kernel(self, base_url: str, token: str, kernel_id: str) -> None:
        headers = {"Authorization": f"token {token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.delete(
                    f"{base_url}/api/kernels/{kernel_id}",
                    headers=headers,
                ) as response:
                    # 404 means the kernel is already gone — treat as success.
                    if response.status not in (200, 202, 204, 404):
                        logger.warning(
                            "Failed to evict local Jupyter kernel %s (status %s)",
                            kernel_id,
                            response.status,
                        )
        except Exception:
            logger.warning("Error while evicting local Jupyter kernel %s", kernel_id)

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
            probe_ok = await self._probe_alive(handle)
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
        if await self._probe_alive(metadata_handle):
            self._handle = metadata_handle
            return
        await self._terminate_pid_unlocked(metadata_handle.pid)
        await self._clear_state_unlocked(pid=metadata_handle.pid)

    async def _start_new_server(
        self,
        *,
        safe_execution: bool = False,
        policy: SandboxAccessPolicy | None = None,
        secure_exec_backend: str = "auto",
    ) -> LocalJupyterHandle:
        ensure_jupyter_dependencies()

        python_executable = self._python_executable()
        working_dir = self._working_dir()
        config_dir = self._config_dir()
        data_dir = self._data_dir()
        runtime_dir = self._runtime_dir()
        shims_dir = self._shims_dir()
        python_environment = self.python_environment()
        working_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        shims_dir.mkdir(parents=True, exist_ok=True)
        python_environment.ensure_command_shims()
        self._write_kernel_spec(
            data_dir=data_dir,
            python_environment=python_environment,
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
        env = python_environment.jupyter_env(
            config_dir=config_dir,
            data_dir=data_dir,
            runtime_dir=runtime_dir,
        )

        log_path = self._log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("ab")
        resolved_secure_exec_backend: str | None = None
        policy_fingerprint: str | None = None
        if safe_execution:
            if policy is None:
                raise RuntimeError("policy is required when safe_execution=True")
            server_policy = policy.model_copy(
                update={"cwd": working_dir, "network_mode": "host"}
            )
            policy_fingerprint = server_policy.fingerprint()
            launch = launch_secure_process(
                SecureProcessConfig(
                    command=command,
                    policy=server_policy,
                    backend=secure_exec_backend,  # type: ignore[arg-type]
                    cwd=working_dir,
                    env=env,
                    stdout=self._log_handle,
                    stderr=subprocess.STDOUT,
                    local_network_port=port,
                    profile_path=self._profile_path(),
                )
            )
            self._proc = launch.process
            resolved_secure_exec_backend = launch.backend
        else:
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
            secure_execution=safe_execution,
            secure_exec_backend=resolved_secure_exec_backend,
            policy_fingerprint=policy_fingerprint,
        )

        try:
            await self._wait_until_ready(
                handle, timeout_sec=self._startup_timeout_sec()
            )
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

    async def _probe_alive(self, handle: LocalJupyterHandle) -> bool:
        """Tolerant liveness check for a server whose pid is already alive.

        Retries with a generous timeout so a momentarily-busy (not dead) server
        isn't declared dead — which would spawn a duplicate and double the load
        on a constrained container.
        """
        timeout = float(
            get_settings().giga_agent_local_jupyter_health_probe_timeout_sec
        )
        for attempt in range(3):
            if await self._probe_server(handle.base_url, handle.token, timeout=timeout):
                return True
            if attempt < 2:
                await asyncio.sleep(0.5)
        return False

    async def _probe_server(
        self, base_url: str, token: str, *, timeout: float = 1.5
    ) -> bool:
        headers = {"Authorization": f"token {token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=timeout)
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
        self._owner_kernels.clear()
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

    def _profile_path(self) -> Path:
        return ensure_giga_agent_dir() / "local_jupyter" / "profiles" / "server.sb"

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
                    "secure_execution": str(handle.secure_execution),
                    "secure_exec_backend": handle.secure_exec_backend or "",
                },
            )
        )

    def _unregister_supervised_process(self, pid: int) -> None:
        get_process_supervisor().unregister_process(kind="local_jupyter", pid=pid)

    def get_shell_env(
        self,
        *,
        extra_envs: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Environment dict for Jupyter-backed local shell sessions."""
        return self.python_environment().shell_env(extra_envs=extra_envs)

    def python_environment(self) -> LocalPythonEnvironment:
        return LocalPythonEnvironment(
            python_executable=self._python_executable(),
            shims_dir=self._shims_dir(),
        )

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

    def _shell_sessions_root(self) -> Path:
        return (ensure_giga_agent_dir() / "local_jupyter" / "shell_sessions").resolve()

    def _kernel_spec_dir(self, *, data_dir: Path) -> Path:
        return (data_dir / "kernels" / LOCAL_JUPYTER_KERNEL_NAME).resolve()

    def _write_kernel_spec(
        self,
        *,
        data_dir: Path,
        python_environment: LocalPythonEnvironment,
    ) -> None:
        kernel_spec_dir = self._kernel_spec_dir(data_dir=data_dir)
        kernel_spec_dir.mkdir(parents=True, exist_ok=True)
        kernel_spec = {
            "argv": [
                python_environment.python_executable,
                "-m",
                "ipykernel_launcher",
                "-f",
                "{connection_file}",
            ],
            "display_name": LOCAL_JUPYTER_KERNEL_DISPLAY_NAME,
            "language": "python",
            "env": python_environment.shell_env(),
            "metadata": {
                "debugger": True,
            },
        }
        (kernel_spec_dir / "kernel.json").write_text(
            json.dumps(kernel_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _python_executable(self) -> str:
        configured = (
            get_settings().giga_agent_local_jupyter_python_executable or ""
        ).strip()
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
                secure_execution=bool(raw_data.get("secure_execution", False)),
                secure_exec_backend=raw_data.get("secure_exec_backend"),
                policy_fingerprint=raw_data.get("policy_fingerprint"),
            )
        except (KeyError, TypeError, ValueError):
            self._remove_metadata_file()
            return None

    def _handle_matches_request(
        self,
        handle: LocalJupyterHandle,
        *,
        safe_execution: bool,
        policy: SandboxAccessPolicy | None,
    ) -> bool:
        if handle.secure_execution != safe_execution:
            return False
        if not safe_execution:
            return True
        if policy is None:
            return False
        requested_policy = policy.model_copy(
            update={"cwd": Path(handle.working_dir), "network_mode": "host"}
        )
        return handle.policy_fingerprint == requested_policy.fingerprint()

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
