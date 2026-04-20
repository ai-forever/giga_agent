"""Shell session management for Docker-based sandboxes."""

import asyncio
import json
import re
import shlex
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from giga_agent.core.logging import get_logger
from giga_agent.sandbox.local_docker.constants import (
    LocalDockerShellMeta,
    _CONTAINER_HOME_DIR,
    _CONTAINER_PYTHON_BIN,
    _SHELL_POLL_INTERVAL_SEC,
    _SHELL_STATUS_COMPLETED,
    _SHELL_STATUS_FAILED,
    _SHELL_STATUS_RUNNING,
)
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellRunResult

logger = get_logger(__name__)


class ShellMixin:
    """Mixin providing shell session lifecycle (run / await / reconcile).

    Expects the host class to also mix in ``ContainerMixin`` and expose:
      - ``_run_exec_in_container(cmd=...)``
      - ``_get_container_file_size(path)``
      - ``_read_container_file_range(path, start, end)``
      - ``_container_process_exists(pid)``
      - ``_decode_container_output(data)``
      - ``_write_shell_meta(meta)``   (provided by this mixin itself)
      - ``_read_shell_meta(shell_id)`` (provided by this mixin itself)
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

        cwd = (working_directory or str(_CONTAINER_HOME_DIR)).strip() or str(
            _CONTAINER_HOME_DIR
        )
        shell_id = uuid.uuid4().hex
        output_path = str(self._shell_log_path(shell_id))
        exit_code_path = str(self._shell_exit_code_path(shell_id))
        meta_path = str(self._shell_meta_path(shell_id))

        await self._initialize_shell_session(shell_id=shell_id)
        pid = await self._start_shell_exec(
            shell_id=shell_id,
            command=command,
            cwd=cwd,
            envs=envs,
        )
        now = self._utc_now_iso()
        meta = LocalDockerShellMeta(
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
            await asyncio.sleep(_SHELL_POLL_INTERVAL_SEC)

        output_size = await self._get_container_file_size(output_path)
        output_bytes = await self._read_container_file_range(output_path, 0, output_size)
        result_output = self._decode_container_output(output_bytes)

        final_meta = current_meta.model_copy(
            update={
                "output_size_bytes": output_size,
                "last_delivered_offset": output_size,
                "last_update_at": self._utc_now_iso(),
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
            output=result_output,
            output_path=output_path,
            meta_path=meta_path,
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
            meta = await self._read_shell_meta(clean_shell_id)
        except FileNotFoundError:
            return ShellAwaitResult(
                shell_id=clean_shell_id,
                status="not_found",
                output_delta="",
                matched_pattern=False,
                output_path=None,
                meta_path=None,
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
                full_output = self._decode_container_output(
                    await self._read_container_file_range(
                        current_meta.output_path,
                        0,
                        await self._get_container_file_size(current_meta.output_path),
                    )
                )
                matched_pattern = compiled_pattern.search(full_output) is not None
            if (
                current_meta.status != _SHELL_STATUS_RUNNING
                or matched_pattern
                or block_until_ms == 0
                or time.monotonic() >= deadline
            ):
                break
            await asyncio.sleep(_SHELL_POLL_INTERVAL_SEC)

        end_offset = await self._get_container_file_size(current_meta.output_path)
        delta_bytes = await self._read_container_file_range(
            current_meta.output_path,
            start_offset,
            end_offset,
        )
        delta_text = self._decode_container_output(delta_bytes)

        updated_meta = current_meta.model_copy(
            update={
                "output_size_bytes": end_offset,
                "last_delivered_offset": end_offset,
                "last_update_at": self._utc_now_iso(),
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
            meta_path=str(self._shell_meta_path(clean_shell_id)),
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
        return _CONTAINER_HOME_DIR / ".giga_agent" / "shell_sessions"

    def _shell_session_dir(self, shell_id: str) -> PurePosixPath:
        return self._shell_sessions_root() / self._validate_shell_id(shell_id)

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
        shell_command = (
            f"mkdir -p {shlex.quote(str(session_dir))} && "
            f": > {shlex.quote(str(output_path))} && "
            f"rm -f {shlex.quote(str(exit_code_path))}"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=["sh", "-lc", shell_command]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to initialize shell session: "
                + self._decode_container_output(output).strip()
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
            f"{command}\n"
            "status=$?\n"
            f"printf '%s\\n' \"$status\" > {shlex.quote(str(exit_code_path))}\n"
            "exit \"$status\"\n"
        )
        script = (
            "import json, os, subprocess, sys\n"
            "cwd = sys.argv[1]\n"
            "output_path = sys.argv[2]\n"
            "command = sys.argv[3]\n"
            "envs = json.loads(sys.argv[4])\n"
            "env = os.environ.copy()\n"
            "env.update({str(k): str(v) for k, v in envs.items()})\n"
            "with open(output_path, 'ab', buffering=0) as output_handle:\n"
            "    process = subprocess.Popen(\n"
            "        ['sh', '-lc', command],\n"
            "        cwd=cwd,\n"
            "        env=env,\n"
            "        stdin=subprocess.DEVNULL,\n"
            "        stdout=output_handle,\n"
            "        stderr=subprocess.STDOUT,\n"
            "        start_new_session=True,\n"
            "    )\n"
            "print(process.pid)\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[
                _CONTAINER_PYTHON_BIN,
                "-c",
                script,
                cwd,
                str(output_path),
                shell_wrapper,
                json.dumps(envs or {}),
            ]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to start shell session: "
                + self._decode_container_output(output).strip()
            )
        pid_text = self._decode_container_output(output).strip()
        try:
            pid = int(pid_text)
        except ValueError as exc:
            raise RuntimeError(f"Failed to parse shell pid: {pid_text!r}") from exc
        if pid <= 0:
            raise RuntimeError(f"Invalid shell pid returned: {pid}")
        return pid

    # ------------------------------------------------------------------
    # meta persistence
    # ------------------------------------------------------------------

    async def _write_shell_meta(self, meta: LocalDockerShellMeta) -> None:
        payload = meta.model_dump(mode="json")
        script = (
            "import json, os, sys, tempfile\n"
            "path = sys.argv[1]\n"
            "payload = json.loads(sys.argv[2])\n"
            "directory = os.path.dirname(path)\n"
            "os.makedirs(directory, exist_ok=True)\n"
            "fd, tmp_path = tempfile.mkstemp(prefix='meta.', suffix='.tmp', dir=directory)\n"
            "try:\n"
            "    with os.fdopen(fd, 'w', encoding='utf-8') as handle:\n"
            "        json.dump(payload, handle, ensure_ascii=False)\n"
            "        handle.write('\\n')\n"
            "        handle.flush()\n"
            "        os.fsync(handle.fileno())\n"
            "    os.replace(tmp_path, path)\n"
            "finally:\n"
            "    if os.path.exists(tmp_path):\n"
            "        os.unlink(tmp_path)\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[
                _CONTAINER_PYTHON_BIN,
                "-c",
                script,
                str(self._shell_meta_path(meta.shell_id)),
                json.dumps(payload, ensure_ascii=False),
            ]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to write shell meta: "
                + self._decode_container_output(output).strip()
            )

    async def _read_shell_meta(self, shell_id: str) -> LocalDockerShellMeta:
        meta_path = str(self._shell_meta_path(shell_id))
        exit_code, output = await self._run_exec_in_container(
            cmd=["cat", "--", meta_path]
        )
        if exit_code != 0:
            error_text = self._decode_container_output(output)
            if "No such file or directory" in error_text:
                raise FileNotFoundError(meta_path)
            raise RuntimeError(f"Failed to read shell meta: {error_text}".strip())
        return LocalDockerShellMeta.model_validate_json(output)

    async def _read_shell_exit_code(self, path: str) -> int | None:
        script = (
            "import sys\n"
            "path = sys.argv[1]\n"
            "try:\n"
            "    with open(path, 'r', encoding='utf-8') as handle:\n"
            "        data = handle.read().strip()\n"
            "except FileNotFoundError:\n"
            "    data = ''\n"
            "if data:\n"
            "    print(data)\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[_CONTAINER_PYTHON_BIN, "-c", script, path]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to read shell exit code: "
                + self._decode_container_output(output).strip()
            )
        text = self._decode_container_output(output).strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError as exc:
            raise RuntimeError(f"Invalid shell exit code value: {text!r}") from exc

    # ------------------------------------------------------------------
    # reconcile
    # ------------------------------------------------------------------

    async def _reconcile_shell_meta(
        self,
        meta: LocalDockerShellMeta,
    ) -> LocalDockerShellMeta:
        if meta.status != _SHELL_STATUS_RUNNING:
            return meta

        output_size = await self._get_container_file_size(meta.output_path)
        exit_code = await self._read_shell_exit_code(
            meta.exit_code_path or str(self._shell_exit_code_path(meta.shell_id))
        )
        if exit_code is None and meta.pid is not None:
            if await self._container_process_exists(meta.pid):
                return meta
        updated_meta = meta.model_copy(
            update={
                "status": (
                    _SHELL_STATUS_COMPLETED
                    if exit_code == 0
                    else _SHELL_STATUS_FAILED
                ),
                "ended_at": self._utc_now_iso(),
                "elapsed_ms": self._elapsed_ms(meta.started_at),
                "exit_code": exit_code,
                "output_size_bytes": output_size,
                "last_update_at": self._utc_now_iso(),
            }
        )
        await self._write_shell_meta(updated_meta)
        return updated_meta

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
