"""Shell session management for E2B sandboxes.

Uses E2B SDK ``commands.run(background=True)`` for background execution
and file-based persistence (output.log, exit_code, meta.json) inside the
sandbox — same layout as local_docker, but without Python helper scripts.
"""

import asyncio
import json
import re
import shlex
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.e2b.constants import (
    _E2B_HOME_DIR,
    _E2B_SHELL_POLL_INTERVAL_SEC,
    _SHELL_STATUS_COMPLETED,
    _SHELL_STATUS_FAILED,
    _SHELL_STATUS_RUNNING,
)
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellMeta, ShellRunResult

logger = get_logger(__name__)


class E2BShellMixin:
    """Mixin providing shell session lifecycle for E2B sandboxes.

    Expects the host class to expose:
      - ``_e2b_sandbox`` — E2B ``AsyncSandbox`` instance
      - ``_ensure_e2b_sandbox_connected()`` — reconnect if needed
    """

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

        await self._ensure_e2b_sandbox_connected()

        cwd = (working_directory or str(_E2B_HOME_DIR)).strip() or str(_E2B_HOME_DIR)
        shell_id = uuid.uuid4().hex
        output_path = str(self._shell_log_path(shell_id))
        exit_code_path = str(self._shell_exit_code_path(shell_id))

        await self._initialize_shell_session(shell_id=shell_id)
        pid = await self._start_shell_exec(
            shell_id=shell_id,
            command=command,
            cwd=cwd,
            envs=envs,
        )

        now = _utc_now_iso()
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
        await self._write_shell_meta(meta)

        deadline = time.monotonic() + (block_until_ms / 1000.0)
        current_meta = meta
        while True:
            current_meta = await self._reconcile_shell_meta(current_meta)
            if current_meta.status != _SHELL_STATUS_RUNNING:
                break
            if block_until_ms == 0 or time.monotonic() >= deadline:
                break
            await asyncio.sleep(_E2B_SHELL_POLL_INTERVAL_SEC)

        output_size = await self._get_e2b_file_size(output_path)
        output_text = await self._read_e2b_file_text(output_path)

        final_meta = current_meta.model_copy(
            update={
                "output_size_bytes": output_size,
                "last_delivered_offset": output_size,
                "last_update_at": _utc_now_iso(),
            }
        )
        await self._write_shell_meta(final_meta)

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
            output=output_text,
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
        clean_shell_id = _validate_shell_id(shell_id)
        if block_until_ms < 0:
            raise ValueError("block_until_ms must be >= 0")

        await self._ensure_e2b_sandbox_connected()

        compiled_pattern = None
        if pattern is not None:
            try:
                compiled_pattern = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid pattern: {exc}") from exc

        try:
            meta = await self._read_shell_meta(clean_shell_id)
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
            current_meta = await self._reconcile_shell_meta(current_meta)
            if compiled_pattern is not None:
                full_output = await self._read_e2b_file_text(current_meta.output_path)
                matched_pattern = compiled_pattern.search(full_output) is not None
            if (
                current_meta.status != _SHELL_STATUS_RUNNING
                or matched_pattern
                or block_until_ms == 0
                or time.monotonic() >= deadline
            ):
                break
            await asyncio.sleep(_E2B_SHELL_POLL_INTERVAL_SEC)

        end_offset = await self._get_e2b_file_size(current_meta.output_path)
        delta_text = await self._read_e2b_file_range_text(
            current_meta.output_path,
            start_offset,
            end_offset,
        )

        updated_meta = current_meta.model_copy(
            update={
                "output_size_bytes": end_offset,
                "last_delivered_offset": end_offset,
                "last_update_at": _utc_now_iso(),
            }
        )
        await self._write_shell_meta(updated_meta)

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

    def _shell_sessions_root(self) -> PurePosixPath:
        return _E2B_HOME_DIR / ".giga_agent" / "shell_sessions"

    def _shell_session_dir(self, shell_id: str) -> PurePosixPath:
        return self._shell_sessions_root() / _validate_shell_id(shell_id)

    def _shell_meta_path(self, shell_id: str) -> PurePosixPath:
        return self._shell_session_dir(shell_id) / "meta.json"

    def _shell_log_path(self, shell_id: str) -> PurePosixPath:
        return self._shell_session_dir(shell_id) / "output.log"

    def _shell_exit_code_path(self, shell_id: str) -> PurePosixPath:
        return self._shell_session_dir(shell_id) / "exit_code"

    # ------------------------------------------------------------------
    # session init / exec start
    # ------------------------------------------------------------------

    async def _initialize_shell_session(self, *, shell_id: str) -> None:
        session_dir = self._shell_session_dir(shell_id)
        output_path = self._shell_log_path(shell_id)
        exit_code_path = self._shell_exit_code_path(shell_id)
        init_cmd = (
            f"mkdir -p {shlex.quote(str(session_dir))} && "
            f": > {shlex.quote(str(output_path))} && "
            f"rm -f {shlex.quote(str(exit_code_path))}"
        )
        result = await self._e2b_sandbox.commands.run(init_cmd)
        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to initialize shell session: {result.stderr}".strip()
            )

    async def _start_shell_exec(
        self,
        *,
        shell_id: str,
        command: str,
        cwd: str,
        envs: dict[str, str] | None = None,
    ) -> int:
        output_path = self._shell_log_path(shell_id)
        exit_code_path = self._shell_exit_code_path(shell_id)

        shell_wrapper = (
            f"exec > {shlex.quote(str(output_path))} 2>&1\n"
            f"{command}\n"
            "status=$?\n"
            f"printf '%s\\n' \"$status\" > {shlex.quote(str(exit_code_path))}\n"
            'exit "$status"\n'
        )

        handle = await self._e2b_sandbox.commands.run(
            f"sh -lc {shlex.quote(shell_wrapper)}",
            background=True,
            cwd=cwd,
            envs=envs or {},
            timeout=0,
        )
        pid = handle.pid
        if not pid or pid <= 0:
            raise RuntimeError(f"Invalid shell pid returned: {pid}")
        return pid

    # ------------------------------------------------------------------
    # meta persistence (via E2B files API)
    # ------------------------------------------------------------------

    async def _write_shell_meta(self, meta: ShellMeta) -> None:
        payload = json.dumps(meta.model_dump(mode="json"), ensure_ascii=False) + "\n"
        meta_path = str(self._shell_meta_path(meta.shell_id))
        await self._e2b_sandbox.files.write(meta_path, payload)

    async def _read_shell_meta(self, shell_id: str) -> ShellMeta:
        meta_path = str(self._shell_meta_path(shell_id))
        try:
            data = await self._e2b_sandbox.files.read(meta_path)
        except Exception as exc:
            err_msg = str(exc)
            if "No such file" in err_msg or "not found" in err_msg.lower():
                raise FileNotFoundError(meta_path) from exc
            raise RuntimeError(f"Failed to read shell meta: {err_msg}".strip()) from exc
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="replace")
        return ShellMeta.model_validate_json(data)

    async def _read_shell_exit_code(self, path: str) -> int | None:
        result = await self._e2b_sandbox.commands.run(
            f"cat {shlex.quote(path)} 2>/dev/null || true"
        )
        text = (result.stdout or "").strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # reconcile
    # ------------------------------------------------------------------

    async def _reconcile_shell_meta(self, meta: ShellMeta) -> ShellMeta:
        if meta.status != _SHELL_STATUS_RUNNING:
            return meta

        output_size = await self._get_e2b_file_size(meta.output_path)

        exit_code = await self._read_shell_exit_code(
            meta.exit_code_path or str(self._shell_exit_code_path(meta.shell_id))
        )
        if exit_code is None and meta.pid is not None:
            if await self._e2b_process_exists(meta.pid):
                return meta

        updated_meta = meta.model_copy(
            update={
                "status": (
                    _SHELL_STATUS_COMPLETED if exit_code == 0 else _SHELL_STATUS_FAILED
                ),
                "ended_at": _utc_now_iso(),
                "elapsed_ms": _elapsed_ms(meta.started_at),
                "exit_code": exit_code,
                "output_size_bytes": output_size,
                "last_update_at": _utc_now_iso(),
            }
        )
        await self._write_shell_meta(updated_meta)
        return updated_meta

    # ------------------------------------------------------------------
    # E2B file I/O helpers
    # ------------------------------------------------------------------

    async def _get_e2b_file_size(self, path: str) -> int:
        result = await self._e2b_sandbox.commands.run(
            f"stat -c%s {shlex.quote(path)} 2>/dev/null || echo 0"
        )
        text = (result.stdout or "0").strip()
        try:
            return int(text)
        except ValueError:
            return 0

    async def _read_e2b_file_text(self, path: str) -> str:
        try:
            data = await self._e2b_sandbox.files.read(path)
        except Exception:
            return ""
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        return str(data)

    async def _read_e2b_file_range_text(self, path: str, start: int, end: int) -> str:
        if start >= end:
            return ""
        count = end - start
        result = await self._e2b_sandbox.commands.run(
            f"dd if={shlex.quote(path)} bs=1 skip={start} count={count} 2>/dev/null"
        )
        return result.stdout or ""

    async def _e2b_process_exists(self, pid: int) -> bool:
        try:
            processes = await self._e2b_sandbox.commands.list()
            return any(p.pid == pid for p in processes)
        except Exception:
            return False


# ------------------------------------------------------------------
# module-level utils
# ------------------------------------------------------------------


def _validate_shell_id(shell_id: str) -> str:
    clean = shell_id.strip()
    path = PurePosixPath(clean)
    if not clean or clean in {".", ".."} or len(path.parts) != 1:
        raise ValueError("shell_id must be a single non-empty path segment")
    return clean


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed_ms(started_at: str) -> int:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
