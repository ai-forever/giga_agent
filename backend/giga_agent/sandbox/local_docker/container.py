"""Low-level Docker container helpers (exec, file I/O, process probing)."""

import time
import uuid
from typing import Any

from docker.errors import DockerException

from giga_agent.core.logging import get_logger
from giga_agent.sandbox.local_docker.constants import _CONTAINER_PYTHON_BIN

logger = get_logger(__name__)


class ContainerMixin:
    """Mixin providing low-level Docker container operations.

    Expects the host class to expose:
      - ``_container`` (docker Container or None)
      - ``external_id`` (str or None)
      - ``_client`` (docker client)
      - ``_reconnect()``
    """

    # ------------------------------------------------------------------
    # exec
    # ------------------------------------------------------------------

    async def _run_exec_in_container(
        self,
        *,
        cmd: list[str] | str,
    ) -> tuple[int, bytes]:
        await self._ensure_container_connected()
        assert self._container is not None
        try:
            exit_code, output = self._container.exec_run(
                cmd=cmd,
                stdout=True,
                stderr=True,
            )
        except DockerException:
            container_status = getattr(self._container, "status", None)
            try:
                self._container.reload()
                container_status = getattr(self._container, "status", container_status)
            except Exception:
                pass
            raise
        return int(exit_code), bytes(output)

    # ------------------------------------------------------------------
    # container file helpers
    # ------------------------------------------------------------------

    async def _get_container_file_size(self, path: str) -> int:
        script = (
            "import os, sys\n"
            "path = sys.argv[1]\n"
            "try:\n"
            "    print(os.path.getsize(path))\n"
            "except FileNotFoundError:\n"
            "    print(0)\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[_CONTAINER_PYTHON_BIN, "-c", script, path]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to read shell log size: "
                + self._decode_container_output(output).strip()
            )
        return int(self._decode_container_output(output).strip() or "0")

    async def _read_container_file_range(
        self,
        path: str,
        start_offset: int,
        end_offset: int | None = None,
    ) -> bytes:
        if start_offset < 0:
            raise ValueError("start_offset must be >= 0")
        if end_offset is not None and end_offset < start_offset:
            return b""
        script = (
            "import os, sys\n"
            "path = sys.argv[1]\n"
            "start = int(sys.argv[2])\n"
            "end_arg = sys.argv[3]\n"
            "end = None if end_arg == '-1' else int(end_arg)\n"
            "try:\n"
            "    with open(path, 'rb') as handle:\n"
            "        handle.seek(start)\n"
            "        data = handle.read() if end is None else handle.read(max(0, end - start))\n"
            "except FileNotFoundError:\n"
            "    data = b''\n"
            "sys.stdout.buffer.write(data)\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[
                _CONTAINER_PYTHON_BIN,
                "-c",
                script,
                path,
                str(start_offset),
                "-1" if end_offset is None else str(end_offset),
            ]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to read container file range: "
                + self._decode_container_output(output).strip()
            )
        return output

    # ------------------------------------------------------------------
    # process probing
    # ------------------------------------------------------------------

    async def _container_process_exists(self, pid: int) -> bool:
        if pid <= 0:
            return False
        script = (
            "import os, sys\n"
            "pid = int(sys.argv[1])\n"
            "try:\n"
            "    os.kill(pid, 0)\n"
            "except ProcessLookupError:\n"
            "    print('0')\n"
            "except PermissionError:\n"
            "    print('1')\n"
            "else:\n"
            "    print('1')\n"
        )
        exit_code, output = await self._run_exec_in_container(
            cmd=[_CONTAINER_PYTHON_BIN, "-c", script, str(pid)]
        )
        if exit_code != 0:
            raise RuntimeError(
                "Failed to probe shell process: "
                + self._decode_container_output(output).strip()
            )
        return self._decode_container_output(output).strip() == "1"

    # ------------------------------------------------------------------
    # container events
    # ------------------------------------------------------------------

    def _collect_recent_container_events(
        self,
        *,
        container_id: str | None,
        since_sec: int = 30,
    ) -> list[dict[str, Any]]:
        if not container_id:
            return []
        now = int(time.time())
        try:
            events = self._client.api.events(
                since=now - since_sec,
                until=now + 1,
                decode=True,
                filters={"type": ["container"], "container": [container_id]},
            )
            collected: list[dict[str, Any]] = []
            for item in events:
                if not isinstance(item, dict):
                    continue
                collected.append(
                    {
                        "status": item.get("status"),
                        "action": item.get("Action"),
                        "time": item.get("time"),
                        "timeNano": item.get("timeNano"),
                        "id": item.get("id"),
                        "actorAttributes": (
                            (item.get("Actor") or {}).get("Attributes") or {}
                        ),
                    }
                )
            return collected[-10:]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # connectivity
    # ------------------------------------------------------------------

    async def _ensure_container_connected(self) -> None:
        if self._container is None and self.external_id:
            await self._reconnect()
        if self._container is None:
            raise RuntimeError("Local docker sandbox is not connected")

    @classmethod
    def _container_is_running(cls, container: Any) -> bool:
        try:
            state = container.attrs.get("State") or {}
            return bool(state.get("Running"))
        except Exception:
            return getattr(container, "status", None) == "running"

    @classmethod
    def _parse_uuid_label(cls, labels: dict[str, str], key: str) -> uuid.UUID | None:
        raw = labels.get(key)
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @staticmethod
    def _get_env_value(container: Any, key: str) -> str | None:
        try:
            env = (container.attrs.get("Config") or {}).get("Env") or []
        except Exception:
            return None
        for item in env:
            if not isinstance(item, str):
                continue
            if item.startswith(f"{key}="):
                return item.split("=", 1)[1]
        return None

    def _decode_container_output(self, data: bytes) -> str:
        return data.decode("utf-8", errors="replace")
