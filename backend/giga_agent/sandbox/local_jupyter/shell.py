"""Shell session management for local Jupyter sandboxes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.core.process_supervisor import (
    ManagedProcessRecord,
    get_process_supervisor,
)
from giga_agent.sandbox.local_jupyter.manager import get_local_jupyter_server_manager
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellMeta, ShellRunResult
from giga_agent.sandbox.secure_exec import SecureProcessConfig, launch_secure_process

logger = get_logger(__name__)

_SHELL_POLL_INTERVAL_SEC = 0.2
_SHELL_STATUS_RUNNING: Literal["running"] = "running"
_SHELL_STATUS_COMPLETED: Literal["completed"] = "completed"
_SHELL_STATUS_FAILED: Literal["failed"] = "failed"
_SHELL_SUPERVISOR_KIND = "local_jupyter_shell"
_SHELL_GRACEFUL_TIMEOUT_SEC = 5.0


class LocalShellMixin:
    """Mixin providing shell session lifecycle for local Jupyter sandboxes.

    Runs commands directly on the host via ``subprocess.Popen`` with
    pip/python shims from ``LocalJupyterServerManager`` prepended to PATH.
    """

    def _get_processes(self) -> dict[str, subprocess.Popen[bytes]]:
        try:
            return self._processes  # type: ignore[attr-defined]
        except AttributeError:
            object.__setattr__(self, "_processes", {})
            return self._processes  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def run_shell(
        self,
        command: str,
        *,
        working_directory: str | None = None,
        block_until_ms: int = 30000,
        description: str | None = None,
        envs: dict[str, str] | None = None,
    ) -> ShellRunResult:
        command = command.strip()
        if not command:
            raise ValueError("command must be a non-empty string")
        if block_until_ms < 0:
            raise ValueError("block_until_ms must be >= 0")

        default_workdir = getattr(self, "_default_workdir", None)
        if getattr(self, "default_cwd", None) and callable(default_workdir):
            default_cwd = str(default_workdir())
        else:
            default_cwd = str(get_local_jupyter_server_manager()._working_dir())
        cwd = (working_directory or default_cwd).strip() or default_cwd

        shell_id = uuid.uuid4().hex
        output_path = str(self._shell_log_path(shell_id))
        exit_code_path = str(self._shell_exit_code_path(shell_id))

        self._initialize_shell_session(shell_id=shell_id)
        pid = self._start_shell_exec(
            shell_id=shell_id,
            command=command,
            cwd=cwd,
            envs=envs,
        )
        self._register_shell_process(shell_id, pid)

        now = self._utc_now_iso()
        meta = ShellMeta(
            shell_id=shell_id,
            command=command,
            description=description,
            cwd=cwd,
            status=_SHELL_STATUS_RUNNING,
            started_at=now,
            pid=pid,
            output_path=output_path,
            exit_code_path=exit_code_path,
            last_update_at=now,
        )
        self._write_shell_meta(meta)

        deadline = time.monotonic() + (block_until_ms / 1000.0)
        current_meta = meta
        while True:
            current_meta = self._reconcile_shell_meta(current_meta)
            if current_meta.status != _SHELL_STATUS_RUNNING:
                break
            if block_until_ms == 0 or time.monotonic() >= deadline:
                break
            await asyncio.sleep(_SHELL_POLL_INTERVAL_SEC)

        output_size = self._get_file_size(output_path)
        result_output = self._read_file_range(output_path, 0, output_size).decode(
            "utf-8", errors="replace"
        )

        final_meta = current_meta.model_copy(
            update={
                "output_size_bytes": output_size,
                "last_delivered_offset": output_size,
                "last_update_at": self._utc_now_iso(),
            }
        )
        self._write_shell_meta(final_meta)

        backgrounded = final_meta.status == _SHELL_STATUS_RUNNING
        await_hint = None
        if backgrounded:
            await_hint = (
                f"Процесс продолжает выполняться. Ты можешь вызвать "
                f'await_shell(shell_id="{shell_id}") для чтения нового вывода.'
            )

        return ShellRunResult(
            shell_id=shell_id,
            status=final_meta.status,
            backgrounded=backgrounded,
            cwd=cwd,
            description=description,
            output=result_output,
            output_path=output_path,
            pid=final_meta.pid,
            exit_code=final_meta.exit_code,
            elapsed_ms=final_meta.elapsed_ms,
            await_hint=await_hint,
        )

    async def await_shell(
        self,
        shell_id: str,
        *,
        block_until_ms: int = 30000,
        pattern: str | None = None,
    ) -> ShellAwaitResult:
        clean_shell_id = self._validate_shell_id(shell_id)
        if block_until_ms < 0:
            raise ValueError("block_until_ms must be >= 0")

        compiled_pattern = None
        if pattern is not None:
            try:
                compiled_pattern = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid pattern: {exc}") from exc

        try:
            meta = self._read_shell_meta(clean_shell_id)
        except FileNotFoundError:
            return ShellAwaitResult(
                shell_id=clean_shell_id,
                status="not_found",
                output_delta="",
                matched_pattern=False,
                output_path=None,
                exit_code=None,
                elapsed_ms=None,
                read_full_log_hint="Shell-сессия не найдена.",
            )

        start_offset = meta.last_delivered_offset
        deadline = time.monotonic() + (block_until_ms / 1000.0)
        matched_pattern = False
        current_meta = meta

        while True:
            current_meta = self._reconcile_shell_meta(current_meta)
            if compiled_pattern is not None:
                output_size = self._get_file_size(current_meta.output_path)
                full_output = self._read_file_range(
                    current_meta.output_path, 0, output_size
                ).decode("utf-8", errors="replace")
                matched_pattern = compiled_pattern.search(full_output) is not None
            if (
                current_meta.status != _SHELL_STATUS_RUNNING
                or matched_pattern
                or block_until_ms == 0
                or time.monotonic() >= deadline
            ):
                break
            await asyncio.sleep(_SHELL_POLL_INTERVAL_SEC)

        end_offset = self._get_file_size(current_meta.output_path)
        delta_bytes = self._read_file_range(
            current_meta.output_path, start_offset, end_offset
        )
        delta_text = delta_bytes.decode("utf-8", errors="replace")

        updated_meta = current_meta.model_copy(
            update={
                "output_size_bytes": end_offset,
                "last_delivered_offset": end_offset,
                "last_update_at": self._utc_now_iso(),
            }
        )
        self._write_shell_meta(updated_meta)

        output_path = updated_meta.output_path
        return ShellAwaitResult(
            shell_id=clean_shell_id,
            status=updated_meta.status,
            output_delta=delta_text,
            matched_pattern=matched_pattern,
            output_path=output_path,
            exit_code=updated_meta.exit_code,
            elapsed_ms=updated_meta.elapsed_ms,
            read_full_log_hint=(
                "Если нужен весь лог, прочитай output.log через read_file: "
                f"{output_path}"
            ),
        )

    # ------------------------------------------------------------------
    # path helpers
    # ------------------------------------------------------------------

    def _shell_sessions_root(self) -> Path:
        manager = get_local_jupyter_server_manager()
        if hasattr(manager, "_shell_sessions_root"):
            return manager._shell_sessions_root()
        return (ensure_giga_agent_dir() / "local_jupyter" / "shell_sessions").resolve()

    def _shell_session_dir(self, shell_id: str) -> Path:
        return self._shell_sessions_root() / self._validate_shell_id(shell_id)

    def _shell_meta_path(self, shell_id: str) -> Path:
        return self._shell_session_dir(shell_id) / "meta.json"

    def _shell_log_path(self, shell_id: str) -> Path:
        return self._shell_session_dir(shell_id) / "output.log"

    def _shell_exit_code_path(self, shell_id: str) -> Path:
        return self._shell_session_dir(shell_id) / "exit_code"

    # ------------------------------------------------------------------
    # session init / exec start
    # ------------------------------------------------------------------

    def _initialize_shell_session(self, *, shell_id: str) -> None:
        session_dir = self._shell_session_dir(shell_id)
        output_path = self._shell_log_path(shell_id)
        exit_code_path = self._shell_exit_code_path(shell_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"")
        exit_code_path.unlink(missing_ok=True)

    def _start_shell_exec(
        self,
        *,
        shell_id: str,
        command: str,
        cwd: str,
        envs: dict[str, str] | None = None,
    ) -> int:
        output_path = self._shell_log_path(shell_id)
        exit_code_path = self._shell_exit_code_path(shell_id)
        env = self._build_shell_env(envs)
        policy = None
        safe_execution = bool(getattr(self, "safe_execution", False))

        if os.name == "nt":
            exit_code_path_escaped = str(exit_code_path).replace("'", "''")
            shell_wrapper = (
                f"{command}\r\n"
                f'echo %ERRORLEVEL% > "{exit_code_path_escaped}"\r\n'
                f"exit /b %ERRORLEVEL%\r\n"
            )
            shell_cmd: list[str] = ["cmd", "/c", shell_wrapper]
        else:
            shell_wrapper = (
                f"{command}\n"
                "status=$?\n"
                f"printf '%s\\n' \"$status\" > {_sh_quote(str(exit_code_path))}\n"
                'exit "$status"\n'
            )
            shell_cmd = ["sh", "-lc", shell_wrapper]

        if safe_execution:
            build_policy = getattr(self, "_build_access_policy")
            policy = build_policy(
                cwd=Path(cwd),
                network_mode=get_settings().giga_agent_local_jupyter_network_mode,
            )
            policy.assert_valid_cwd(require_writable=True)
            policy.assert_can_write(output_path)
            policy.assert_can_write(exit_code_path)

        output_handle = open(output_path, "ab", buffering=0)  # noqa: SIM115
        try:
            if safe_execution and policy is not None:
                launch = launch_secure_process(
                    SecureProcessConfig(
                        command=shell_cmd,
                        policy=policy,
                        backend=get_settings().giga_agent_local_jupyter_secure_exec_backend,  # type: ignore[arg-type]
                        cwd=Path(cwd),
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=output_handle,
                        stderr=subprocess.STDOUT,
                    )
                )
                process = launch.process
            else:
                process = subprocess.Popen(
                    shell_cmd,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception:
            output_handle.close()
            raise

        self._get_processes()[shell_id] = process
        return process.pid

    def _build_shell_env(self, envs: dict[str, str] | None = None) -> dict[str, str]:
        manager = get_local_jupyter_server_manager()
        env = manager.get_shell_env()
        if envs:
            env.update({str(k): str(v) for k, v in envs.items()})
        return env

    # ------------------------------------------------------------------
    # ProcessSupervisor integration
    # ------------------------------------------------------------------

    def _register_shell_process(self, shell_id: str, pid: int) -> None:
        pgid = self._process_group_id(pid)
        try:
            get_process_supervisor().register_process(
                ManagedProcessRecord(
                    kind=_SHELL_SUPERVISOR_KIND,
                    pid=pid,
                    pgid=pgid,
                    graceful_timeout_sec=_SHELL_GRACEFUL_TIMEOUT_SEC,
                    metadata={"shell_id": shell_id},
                )
            )
        except Exception:
            logger.warning(
                "Failed to register shell process in supervisor: "
                f"shell_id={shell_id} pid={pid}",
                exc_info=True,
            )

    def _unregister_shell_process(self, pid: int) -> None:
        try:
            get_process_supervisor().unregister_process(
                kind=_SHELL_SUPERVISOR_KIND, pid=pid
            )
        except Exception:
            logger.warning(
                f"Failed to unregister shell process from supervisor: pid={pid}",
                exc_info=True,
            )

    def _is_supervised_shell_process(self, pid: int) -> bool:
        try:
            records = get_process_supervisor().list_processes()
            return any(
                r.kind == _SHELL_SUPERVISOR_KIND and r.pid == pid for r in records
            )
        except Exception:
            return False

    def _process_group_id(self, pid: int) -> int | None:
        if pid <= 0:
            return None
        if os.name == "nt":
            return pid
        try:
            return int(os.getpgid(pid))
        except OSError:
            return None

    # ------------------------------------------------------------------
    # meta persistence
    # ------------------------------------------------------------------

    def _write_shell_meta(self, meta: ShellMeta) -> None:
        path = self._shell_meta_path(meta.shell_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = meta.model_dump(mode="json")
        fd, tmp_path = tempfile.mkstemp(
            prefix="meta.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _read_shell_meta(self, shell_id: str) -> ShellMeta:
        path = self._shell_meta_path(shell_id)
        try:
            data = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise RuntimeError(f"Failed to read shell meta: {exc}") from exc
        return ShellMeta.model_validate_json(data)

    def _read_shell_exit_code(self, path: str) -> int | None:
        try:
            data = Path(path).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        if not data:
            return None
        try:
            return int(data)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # reconcile
    # ------------------------------------------------------------------

    def _reconcile_shell_meta(
        self,
        meta: ShellMeta,
    ) -> ShellMeta:
        if meta.status != _SHELL_STATUS_RUNNING:
            return meta

        exit_code_file_path = meta.exit_code_path or str(
            self._shell_exit_code_path(meta.shell_id)
        )

        processes = self._get_processes()
        popen = processes.get(meta.shell_id)
        if popen is not None:
            rc = popen.poll()
            if rc is None:
                return meta
            exit_code = self._read_shell_exit_code(exit_code_file_path)
            if exit_code is None:
                exit_code = rc
        else:
            exit_code = self._read_shell_exit_code(exit_code_file_path)
            if exit_code is None:
                if meta.pid is not None and self._is_supervised_shell_process(meta.pid):
                    if self._is_pid_alive(meta.pid):
                        return meta
                # Popen lost and PID not in supervisor -- consider failed.

        output_size = self._get_file_size(meta.output_path)
        updated_meta = meta.model_copy(
            update={
                "status": (
                    _SHELL_STATUS_COMPLETED if exit_code == 0 else _SHELL_STATUS_FAILED
                ),
                "ended_at": self._utc_now_iso(),
                "elapsed_ms": self._elapsed_ms(meta.started_at),
                "exit_code": exit_code,
                "output_size_bytes": output_size,
                "last_update_at": self._utc_now_iso(),
            }
        )
        self._write_shell_meta(updated_meta)
        if meta.pid is not None:
            self._unregister_shell_process(meta.pid)
        processes.pop(meta.shell_id, None)
        return updated_meta

    # ------------------------------------------------------------------
    # file I/O helpers
    # ------------------------------------------------------------------

    def _get_file_size(self, path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _read_file_range(self, path: str, start: int, end: int) -> bytes:
        if start >= end:
            return b""
        try:
            with open(path, "rb") as f:
                f.seek(start)
                return f.read(end - start)
        except OSError:
            return b""

    # ------------------------------------------------------------------
    # utils
    # ------------------------------------------------------------------

    def _validate_shell_id(self, shell_id: str) -> str:
        clean = shell_id.strip()
        path = PurePosixPath(clean)
        if not clean or clean in {".", ".."} or len(path.parts) != 1:
            raise ValueError("shell_id must be a single non-empty path segment")
        return clean

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _elapsed_ms(self, started_at: str) -> int:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    def _is_pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def _sh_quote(s: str) -> str:
    """Shell-quote a string for POSIX sh."""
    return "'" + s.replace("'", "'\\''") + "'"
