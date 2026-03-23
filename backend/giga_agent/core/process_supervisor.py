from __future__ import annotations

import json
import os
import signal
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from giga_agent.core.logging import get_logger
from giga_agent.core.paths import ensure_giga_agent_dir

logger = get_logger(__name__)

ProcessStopStrategy = Literal["term_then_kill"]
_REGISTRY_VERSION = 1
_LOCK_STALE_TIMEOUT_SEC = 30.0
_LOCK_POLL_INTERVAL_SEC = 0.05


@dataclass(slots=True)
class ManagedProcessRecord:
    kind: str
    pid: int
    pgid: int | None
    stop_strategy: ProcessStopStrategy = "term_then_kill"
    graceful_timeout_sec: float = 5.0
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = dict(self.metadata)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ManagedProcessRecord:
        return cls(
            kind=str(raw["kind"]),
            pid=int(raw["pid"]),
            pgid=None if raw.get("pgid") is None else int(raw["pgid"]),
            stop_strategy=str(raw.get("stop_strategy", "term_then_kill")),  # type: ignore[arg-type]
            graceful_timeout_sec=float(raw.get("graceful_timeout_sec", 5.0)),
            metadata=(
                dict(raw["metadata"])
                if isinstance(raw.get("metadata"), dict)
                else {}
            ),
            registered_at=float(raw.get("registered_at", time.time())),
        )


class ProcessSupervisor:
    def __init__(self, *, runtime_dir: Path | None = None) -> None:
        base_dir = runtime_dir or (ensure_giga_agent_dir() / "process_supervisor")
        self._runtime_dir = base_dir.resolve()
        self._registry_path = self._runtime_dir / "processes.json"
        self._lock_path = self._runtime_dir / "processes.lock"

    def register_process(self, record: ManagedProcessRecord) -> None:
        def _mutate(records: list[ManagedProcessRecord]) -> list[ManagedProcessRecord]:
            filtered = [
                item
                for item in records
                if not (item.kind == record.kind and item.pid == record.pid)
            ]
            filtered.append(record)
            return filtered

        self._update_records(_mutate)

    def unregister_process(self, *, kind: str, pid: int) -> None:
        def _mutate(records: list[ManagedProcessRecord]) -> list[ManagedProcessRecord]:
            return [
                item for item in records if not (item.kind == kind and item.pid == pid)
            ]

        self._update_records(_mutate)

    def list_processes(self, *, cleanup_stale: bool = False) -> list[ManagedProcessRecord]:
        records = self._read_records()
        if not cleanup_stale:
            return records
        alive_records = [record for record in records if self._is_pid_alive(record.pid)]
        if len(alive_records) != len(records):
            self._write_records(alive_records)
        return alive_records

    def stop_all(self, *, kinds: set[str] | None = None) -> list[ManagedProcessRecord]:
        records = self.list_processes(cleanup_stale=True)
        stopped: list[ManagedProcessRecord] = []
        for record in records:
            if kinds is not None and record.kind not in kinds:
                continue
            if not self._is_pid_alive(record.pid):
                self.unregister_process(kind=record.kind, pid=record.pid)
                continue
            self._stop_record(record)
            if not self._is_pid_alive(record.pid):
                self.unregister_process(kind=record.kind, pid=record.pid)
            else:
                logger.warning(
                    "Managed process is still alive after supervisor stop attempt: "
                    f"kind={record.kind} pid={record.pid}"
                )
            stopped.append(record)
        return stopped

    @contextmanager
    def _locked_registry(self):
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        lock_fd: int | None = None
        while lock_fd is None:
            try:
                lock_fd = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(lock_fd, str(os.getpid()).encode("ascii", "ignore"))
            except FileExistsError:
                self._cleanup_stale_lock_if_needed()
                time.sleep(_LOCK_POLL_INTERVAL_SEC)
        try:
            yield
        finally:
            try:
                if lock_fd is not None:
                    os.close(lock_fd)
            finally:
                try:
                    self._lock_path.unlink(missing_ok=True)
                except Exception:
                    logger.warning("Failed to remove process supervisor lock file")

    def _cleanup_stale_lock_if_needed(self) -> None:
        try:
            stat = self._lock_path.stat()
        except FileNotFoundError:
            return

        lock_age_sec = time.time() - stat.st_mtime
        try:
            lock_pid = int(self._lock_path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            lock_pid = 0

        if lock_pid > 0 and self._is_pid_alive(lock_pid):
            return
        if lock_age_sec < _LOCK_STALE_TIMEOUT_SEC and lock_pid <= 0:
            return
        try:
            self._lock_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to clean up stale process supervisor lock file")

    def _update_records(
        self,
        mutator: Callable[[list[ManagedProcessRecord]], list[ManagedProcessRecord]],
    ) -> None:
        with self._locked_registry():
            records = self._read_records_unlocked()
            self._write_records_unlocked(mutator(records))

    def _read_records(self) -> list[ManagedProcessRecord]:
        with self._locked_registry():
            return self._read_records_unlocked()

    def _write_records(self, records: list[ManagedProcessRecord]) -> None:
        with self._locked_registry():
            self._write_records_unlocked(records)

    def _read_records_unlocked(self) -> list[ManagedProcessRecord]:
        if not self._registry_path.is_file():
            return []
        try:
            raw = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read process supervisor registry file")
            return []

        if not isinstance(raw, dict):
            return []
        if int(raw.get("version", _REGISTRY_VERSION)) != _REGISTRY_VERSION:
            logger.warning("Unsupported process supervisor registry version")
            return []
        raw_processes = raw.get("processes")
        if not isinstance(raw_processes, list):
            return []

        records: list[ManagedProcessRecord] = []
        for item in raw_processes:
            if not isinstance(item, dict):
                continue
            try:
                records.append(ManagedProcessRecord.from_dict(item))
            except Exception:
                logger.warning("Failed to decode process supervisor record")
        return records

    def _write_records_unlocked(self, records: list[ManagedProcessRecord]) -> None:
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _REGISTRY_VERSION,
            "processes": [record.to_dict() for record in records],
        }
        fd, temp_path_raw = tempfile.mkstemp(
            dir=str(self._runtime_dir),
            prefix="processes.",
            suffix=".tmp",
        )
        temp_path = Path(temp_path_raw)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._registry_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _stop_record(self, record: ManagedProcessRecord) -> None:
        if record.stop_strategy != "term_then_kill":
            logger.warning(
                f"Unsupported process supervisor stop strategy: {record.stop_strategy}"
            )
            return

        self._terminate_record(record, force=False)
        if self._wait_for_exit(record.pid, record.graceful_timeout_sec):
            return
        self._terminate_record(record, force=True)
        self._wait_for_exit(record.pid, 1.0)

    def _terminate_record(self, record: ManagedProcessRecord, *, force: bool) -> None:
        if not self._is_pid_alive(record.pid):
            return
        if os.name == "nt":
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.kill(record.pid, sig)
            except OSError:
                return
            return

        target_pgid = record.pgid
        if target_pgid is None:
            try:
                target_pgid = int(os.getpgid(record.pid))
            except OSError:
                target_pgid = None
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            if target_pgid is not None:
                os.killpg(target_pgid, sig)
            else:
                os.kill(record.pid, sig)
        except OSError:
            return

    def _wait_for_exit(self, pid: int, timeout_sec: float) -> bool:
        started_at = time.monotonic()
        while time.monotonic() - started_at < timeout_sec:
            if not self._is_pid_alive(pid):
                return True
            time.sleep(0.1)
        return not self._is_pid_alive(pid)

    def _is_pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


_SUPERVISOR: ProcessSupervisor | None = None


def get_process_supervisor() -> ProcessSupervisor:
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = ProcessSupervisor()
    return _SUPERVISOR
