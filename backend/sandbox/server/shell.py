"""Native shell-session registry.

В отличие от giga_agent.sandbox.local_docker.shell (который гоняет ``python -c``
на каждую операцию и перечитывает весь лог на каждом poll — O(n^2)), здесь
сессии живут в памяти процесса, вывод пишется напрямую в файл, а чтение идёт
по offset (seek). Это чинит и чаттивность, и OOM, и квадратичный pattern-scan.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from .config import Settings, get_settings
from .models import ShellAwaitResult, ShellMeta, ShellRunResult

_STATUS_RUNNING = "running"
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"
_POLL_INTERVAL_SEC = 0.1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed_ms(started_monotonic: float) -> int:
    return int((time.monotonic() - started_monotonic) * 1000)


@dataclass(slots=True)
class ShellSession:
    shell_id: str
    command: str
    description: str | None
    cwd: str
    output_path: str
    started_at_iso: str
    started_monotonic: float
    proc: asyncio.subprocess.Process
    log_handle: IO[bytes]
    status: str = _STATUS_RUNNING
    exit_code: int | None = None
    ended_at_iso: str | None = None
    elapsed_ms: int | None = None
    last_delivered_offset: int = 0
    _waiter: asyncio.Task | None = field(default=None)

    @property
    def pid(self) -> int | None:
        return self.proc.pid

    def output_size(self) -> int:
        try:
            return os.path.getsize(self.output_path)
        except OSError:
            return 0

    def to_meta(self) -> ShellMeta:
        return ShellMeta(
            shell_id=self.shell_id,
            command=self.command,
            description=self.description,
            cwd=self.cwd,
            status=self.status,  # type: ignore[arg-type]
            started_at=self.started_at_iso,
            ended_at=self.ended_at_iso,
            elapsed_ms=self.elapsed_ms,
            exit_code=self.exit_code,
            pid=self.pid,
            output_path=self.output_path,
            output_size_bytes=self.output_size(),
            last_update_at=_utc_now_iso(),
        )


class ShellManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._sessions: dict[str, ShellSession] = {}
        self._root = Path(self._settings.shell_sessions_root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # run
    # ------------------------------------------------------------------ #

    async def run(
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

        cwd = (working_directory or self._settings.workdir).strip() or self._settings.workdir
        shell_id = uuid.uuid4().hex
        session_dir = self._root / shell_id
        session_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(session_dir / "output.log")

        env = os.environ.copy()
        if envs:
            env.update({str(k): str(v) for k, v in envs.items()})

        log_handle = open(output_path, "wb", buffering=0)
        proc = await asyncio.create_subprocess_exec(
            "sh",
            "-lc",
            command,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,  # свой process group -> корректный kill детей
        )

        session = ShellSession(
            shell_id=shell_id,
            command=command,
            description=description,
            cwd=cwd,
            output_path=output_path,
            started_at_iso=_utc_now_iso(),
            started_monotonic=time.monotonic(),
            proc=proc,
            log_handle=log_handle,
        )
        session._waiter = asyncio.create_task(self._await_exit(session))
        self._sessions[shell_id] = session

        deadline = time.monotonic() + block_until_ms / 1000.0
        while session.status == _STATUS_RUNNING:
            if block_until_ms == 0 or time.monotonic() >= deadline:
                break
            await asyncio.sleep(_POLL_INTERVAL_SEC)

        size = session.output_size()
        output_text = self._read_range(session.output_path, 0, size)
        session.last_delivered_offset = size

        backgrounded = session.status == _STATUS_RUNNING
        await_hint = (
            f'Процесс продолжает выполняться. Вызови await_shell(shell_id="{shell_id}") '
            "для чтения нового вывода."
            if backgrounded
            else None
        )
        return ShellRunResult(
            shell_id=shell_id,
            status=session.status,  # type: ignore[arg-type]
            backgrounded=backgrounded,
            cwd=cwd,
            description=description,
            output=output_text,
            output_path=session.output_path,
            pid=session.pid,
            exit_code=session.exit_code,
            elapsed_ms=session.elapsed_ms,
            await_hint=await_hint,
        )

    # ------------------------------------------------------------------ #
    # await
    # ------------------------------------------------------------------ #

    async def await_shell(
        self,
        shell_id: str,
        *,
        block_until_ms: int = 30000,
        pattern: str | None = None,
    ) -> ShellAwaitResult:
        if block_until_ms < 0:
            raise ValueError("block_until_ms must be >= 0")
        session = self._sessions.get(shell_id)
        if session is None:
            return ShellAwaitResult(
                shell_id=shell_id,
                status="not_found",
                output_delta="",
                matched_pattern=False,
                read_full_log_hint="Shell-сессия не найдена.",
            )

        compiled = re.compile(pattern) if pattern else None
        start_offset = session.last_delivered_offset
        deadline = time.monotonic() + block_until_ms / 1000.0
        matched = False
        scan_offset = start_offset
        accumulated = ""

        while True:
            if compiled is not None:
                size = session.output_size()
                if size > scan_offset:
                    accumulated += self._read_range(session.output_path, scan_offset, size)
                    scan_offset = size
                matched = compiled.search(accumulated) is not None
            if (
                session.status != _STATUS_RUNNING
                or matched
                or block_until_ms == 0
                or time.monotonic() >= deadline
            ):
                break
            await asyncio.sleep(_POLL_INTERVAL_SEC)

        end_offset = session.output_size()
        delta = self._read_range(session.output_path, start_offset, end_offset)
        session.last_delivered_offset = end_offset

        return ShellAwaitResult(
            shell_id=shell_id,
            status=session.status,  # type: ignore[arg-type]
            output_delta=delta,
            matched_pattern=matched,
            output_path=session.output_path,
            exit_code=session.exit_code,
            elapsed_ms=session.elapsed_ms,
            read_full_log_hint=(
                f"Если нужен весь лог — прочитай output.log через /v1/files: {session.output_path}"
            ),
        )

    # ------------------------------------------------------------------ #
    # list / kill
    # ------------------------------------------------------------------ #

    def list(self, *, only_running: bool = False) -> list[ShellMeta]:
        metas = [s.to_meta() for s in self._sessions.values()]
        if only_running:
            metas = [m for m in metas if m.status == _STATUS_RUNNING]
        return metas

    def get(self, shell_id: str) -> ShellSession | None:
        return self._sessions.get(shell_id)

    async def kill(self, shell_id: str) -> tuple[bool, ShellSession | None]:
        session = self._sessions.get(shell_id)
        if session is None:
            return False, None
        if session.status != _STATUS_RUNNING:
            return False, session
        try:
            pgid = os.getpgid(session.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                session.proc.kill()
            except ProcessLookupError:
                pass
        # дождёмся, чтобы _await_exit проставил статус
        if session._waiter is not None:
            try:
                await asyncio.wait_for(asyncio.shield(session._waiter), timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                pass
        return True, session

    async def shutdown_all(self) -> None:
        for shell_id in list(self._sessions):
            await self.kill(shell_id)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    async def _await_exit(self, session: ShellSession) -> None:
        code = await session.proc.wait()
        session.exit_code = code
        session.status = _STATUS_COMPLETED if code == 0 else _STATUS_FAILED
        session.ended_at_iso = _utc_now_iso()
        session.elapsed_ms = _elapsed_ms(session.started_monotonic)
        try:
            session.log_handle.flush()
            session.log_handle.close()
        except Exception:
            pass

    def _read_range(self, path: str, start: int, end: int) -> str:
        if end <= start:
            return ""
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                data = handle.read(end - start)
        except FileNotFoundError:
            return ""
        return data.decode("utf-8", errors="replace")
