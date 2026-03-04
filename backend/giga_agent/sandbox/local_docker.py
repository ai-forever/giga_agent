import asyncio
import mimetypes
import secrets
import shlex
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import docker
from docker.errors import NotFound
from docker.types import Ulimit
from pydantic import Field, PrivateAttr

from giga_agent.conf import (
    get_local_docker_max_active_sandboxes_from_env,
    get_settings,
)
from giga_agent.core.logging import get_logger
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    StreamResult,
)
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.registry import SandboxRegistry

logger = get_logger(__name__)

JUPYTER_PORT = 8888
BUCKET_PREFIX = "/bucket/"


@SandboxRegistry.register("local_docker")
class LocalDockerSandbox(JupyterSandbox):
    image: str = Field(
        default="mikelarg/code-interpreter:0.0.4",
        description="Docker image to run for local sandbox",
    )

    owner_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Sandbox owner id injected by runtime factory",
    )

    memory_limit_mb: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_memory_limit_mb,
        description="Container memory hard limit in MB",
    )
    memory_reservation_mb: int = Field(
        default_factory=lambda: (
            get_settings().giga_agent_local_docker_memory_reservation_mb
        ),
        description="Container memory soft reservation in MB",
    )
    vcpu: float = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_vcpu,
        description="Container CPU quota in vCPU units",
    )
    pids_limit: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_pids_limit,
        description="Maximum number of processes in container",
    )
    shm_size_mb: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_shm_size_mb,
        description="Container /dev/shm size in MB",
    )
    nofile_soft: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_nofile_soft,
        description="Soft nofile ulimit for container",
    )
    nofile_hard: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_nofile_hard,
        description="Hard nofile ulimit for container",
    )
    startup_timeout_sec: int = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_startup_timeout_sec,
        description="Timeout in seconds to wait for Jupyter startup",
    )
    max_active_sandboxes: int | None = Field(
        default_factory=lambda: (
            get_settings().giga_agent_local_docker_max_active_sandboxes
        ),
        description="Maximum active local sandboxes for this provider",
    )
    enforce_readonly_rootfs: bool = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_readonly_rootfs,
        description="Run container with readonly root filesystem",
    )
    allow_network: bool = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_allow_network,
        description="Allow container network access",
    )

    external_id: Optional[str] = Field(
        default=None,
        description="Docker container ID",
    )
    jupyter_token: Optional[str] = Field(
        default=None,
        description="Jupyter auth token",
    )
    host_port: Optional[int] = Field(
        default=None,
        description="Mapped host port for Jupyter",
    )

    base_url: str = Field(
        default="",
        description="Base URL of local Jupyter server",
    )

    _runtime_fields = JupyterSandbox._runtime_fields | {
        "jupyter_token",
        "host_port",
        "owner_id",
    }

    _client: Any = PrivateAttr(default=None)
    _container: Any = PrivateAttr(default=None)
    _sandbox_root_dir: Path = PrivateAttr(default_factory=Path)

    def model_post_init(self, __context: Any) -> None:
        self._client = docker.from_env()
        root_dir = get_settings().giga_agent_local_docker_files_path
        if root_dir is None:
            root_dir = ensure_giga_agent_dir() / "sandboxes"
        self._sandbox_root_dir = root_dir
        if self.jupyter_token:
            self._token = self.jupyter_token

    @classmethod
    def has_limit_cls(cls) -> bool:
        return True

    def get_connection_settings(self) -> dict:
        return {
            "external_id": self.external_id,
            "jupyter_token": self._token,
            "host_port": self.host_port,
        }

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        validated = await super().validate_settings(settings)
        cls._check_docker_connection()

        def _require_positive(name: str) -> None:
            value = validated.get(name)
            if value is None or value <= 0:
                raise ValueError(f"{name} must be > 0")

        for field_name in (
            "memory_limit_mb",
            "memory_reservation_mb",
            "vcpu",
            "pids_limit",
            "shm_size_mb",
            "nofile_soft",
            "nofile_hard",
            "startup_timeout_sec",
        ):
            _require_positive(field_name)

        if validated["memory_reservation_mb"] > validated["memory_limit_mb"]:
            raise ValueError("memory_reservation_mb must be <= memory_limit_mb")
        if validated["nofile_soft"] > validated["nofile_hard"]:
            raise ValueError("nofile_soft must be <= nofile_hard")

        if validated.get("max_active_sandboxes") is None:
            env_limit = get_local_docker_max_active_sandboxes_from_env()
            if env_limit is not None:
                validated["max_active_sandboxes"] = env_limit

        if validated.get("max_active_sandboxes") is None:
            raise ValueError(
                "max_active_sandboxes is required for local_docker "
                "(provide in settings or set GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES)"
            )
        if validated["max_active_sandboxes"] <= 0:
            raise ValueError("max_active_sandboxes must be > 0")

        return validated

    @staticmethod
    def _check_docker_connection() -> None:
        client = None
        try:
            client = docker.from_env()
            client.ping()
        except Exception as e:
            raise ValueError(f"Docker connection check failed: {e}") from e
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    async def up(self) -> None:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required for local_docker runtime")

        self._token = secrets.token_urlsafe(13)
        self.jupyter_token = self._token

        user_root = self._user_root_dir(self.owner_id)
        user_root.mkdir(parents=True, exist_ok=True)

        envs = {
            "JUPYTER_TOKEN": self._token,
            "JUPYTER_RUNTIME_DIR": "/tmp/jupyter_runtime",
            "IPYTHONDIR": "/tmp/ipython",
            "MATPLOTLIBRC": "/tmp/matplotlibrc",
        }
        docker_path = str(
            Path("/Users/mikelarg/PycharmProjects/giga_agent")
            / str(user_root).lstrip("\/")
        )
        run_kwargs: dict[str, Any] = {
            "command": "sleep infinity",
            "detach": True,
            "remove": True,
            "environment": envs,
            "ports": {f"{JUPYTER_PORT}/tcp": None},
            "volumes": {
                str(user_root): {"bind": BUCKET_PREFIX.rstrip("/"), "mode": "rw"}
            },
            "nano_cpus": int(self.vcpu * 1_000_000_000),
            "mem_limit": f"{self.memory_limit_mb}m",
            "mem_reservation": f"{self.memory_reservation_mb}m",
            "pids_limit": self.pids_limit,
            "shm_size": f"{self.shm_size_mb}m",
            "ulimits": [
                Ulimit(name="nofile", soft=self.nofile_soft, hard=self.nofile_hard)
            ],
            "read_only": self.enforce_readonly_rootfs,
        }
        if not self.allow_network:
            run_kwargs["network_mode"] = "none"
        if self.enforce_readonly_rootfs:
            run_kwargs["tmpfs"] = {
                "/tmp": "rw,exec,nosuid,size=512m",
                "/run": "rw,nosuid,size=64m",
                "/var/run": "rw,nosuid,size=64m",
            }

        logger.info(
            "Starting local sandbox container owner=%s image=%s mem=%sMB vcpu=%s",
            self.owner_id,
            self.image,
            self.memory_limit_mb,
            self.vcpu,
        )
        self._container = self._client.containers.run(self.image, **run_kwargs)

        self.external_id = self._container.id
        self._container.reload()
        ports = self._container.attrs["NetworkSettings"]["Ports"]
        binding = ports.get(f"{JUPYTER_PORT}/tcp")
        if not binding:
            raise RuntimeError(f"Could not find mapped port for {JUPYTER_PORT}")

        self.host_port = int(binding[0]["HostPort"])
        self.base_url = f"http://localhost:{self.host_port}"

        cmd = (
            f"jupyter server --ip=0.0.0.0 --port={JUPYTER_PORT} --allow-root "
            '--ServerApp.token="${JUPYTER_TOKEN}" > /dev/null 2>&1 &'
        )
        self._container.exec_run(f"sh -c {shlex.quote(cmd)}", detach=True)

        start = time.time()
        while True:
            if await self.is_up():
                return
            if time.time() - start > self.startup_timeout_sec:
                raise TimeoutError(
                    f"Jupyter did not start within {self.startup_timeout_sec} seconds"
                )
            await asyncio.sleep(1)

    async def stop(self) -> None:
        container = self._container
        if container is None and self.external_id:
            try:
                container = self._client.containers.get(self.external_id)
            except NotFound:
                container = None

        if container is not None:
            logger.info("Stopping local sandbox container %s", container.id[:12])
            try:
                container.stop(timeout=5)
            except NotFound:
                pass

        self._container = None

    async def _reconnect(self) -> None:
        if not self.external_id:
            return
        try:
            self._container = self._client.containers.get(self.external_id)
            if self.host_port:
                self.base_url = f"http://localhost:{self.host_port}"
        except NotFound:
            self._container = None

    async def is_up(self) -> bool:
        if not self.base_url and self.host_port:
            self.base_url = f"http://localhost:{self.host_port}"
        if not self.base_url and self.external_id:
            await self._reconnect()
        if not self.base_url:
            return False
        return await super().is_up()

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        rel_path = self._validate_relative_file_name(file_name)
        target = self._user_root_dir(owner_id) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"{BUCKET_PREFIX}{rel_path.as_posix()}"

    def requires_running_for_upload(self) -> bool:
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        if self._is_bucket_path(sandbox_path):
            local_path = self._local_path_from_bucket_path(sandbox_path)
            if not local_path.exists() or not local_path.is_file():
                raise FileNotFoundError(f"File not found: {sandbox_path}")

            media_type, _ = mimetypes.guess_type(local_path.name)
            if not media_type:
                media_type = "application/octet-stream"
            inline = local_path.suffix.lower() in {".html", ".htm"}

            size = local_path.stat().st_size
            if size >= LARGE_FILE_THRESHOLD:
                return StreamResult(
                    stream=self._stream_local_file(local_path),
                    media_type=media_type,
                    inline=inline,
                    content_length=size,
                )

            data = local_path.read_bytes()
            return ContentResult(data=data, media_type=media_type, inline=inline)

        await self._ensure_container_connected()
        assert self._container is not None
        exit_code, output = self._container.exec_run(
            cmd=["cat", "--", sandbox_path],
            stdout=True,
            stderr=True,
        )
        if exit_code != 0:
            stderr = output.decode(errors="ignore")
            if "No such file or directory" in stderr:
                raise FileNotFoundError(f"File not found: {sandbox_path}")
            raise RuntimeError(
                f"Failed to read file '{sandbox_path}': {stderr}".strip()
            )

        media_type, _ = mimetypes.guess_type(sandbox_path)
        return ContentResult(
            data=bytes(output), media_type=media_type or "application/octet-stream"
        )

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        return not self._is_bucket_path(sandbox_path)

    async def delete_file(self, sandbox_path: str) -> None:
        if self._is_bucket_path(sandbox_path):
            local_path = self._local_path_from_bucket_path(sandbox_path)
            if local_path.exists():
                local_path.unlink()
            return

        await self._ensure_container_connected()
        assert self._container is not None
        exit_code, output = self._container.exec_run(
            cmd=["rm", "-f", "--", sandbox_path],
            stdout=True,
            stderr=True,
        )
        if exit_code != 0:
            stderr = output.decode(errors="ignore")
            raise RuntimeError(
                f"Failed to delete file '{sandbox_path}': {stderr}".strip()
            )

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        return not self._is_bucket_path(sandbox_path)

    def _is_bucket_path(self, path: str) -> bool:
        return path.startswith(BUCKET_PREFIX)

    async def _stream_local_file(
        self, path: Path, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        with path.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0)

    def _validate_relative_file_name(self, file_name: str) -> PurePosixPath:
        clean = file_name.strip().replace("\\", "/").lstrip("/")
        path = PurePosixPath(clean)
        if path.name in {"", ".", ".."}:
            raise ValueError("file_name must contain a valid file name")
        if any(part in {".", ".."} for part in path.parts):
            raise ValueError("file_name must not contain '.' or '..' path segments")
        return path

    def _user_root_dir(self, owner_id: uuid.UUID) -> Path:
        root = self._sandbox_root_dir
        root.mkdir(parents=True, exist_ok=True)
        user_root = (root / str(owner_id)).resolve()
        user_root.mkdir(parents=True, exist_ok=True)
        return user_root

    def _local_path_from_bucket_path(self, sandbox_path: str) -> Path:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required to resolve sandbox path")
        key = sandbox_path[len(BUCKET_PREFIX) :].strip("/")
        if not key:
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        rel = PurePosixPath(key)
        if any(part in {".", ".."} for part in rel.parts):
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        user_root = self._user_root_dir(self.owner_id).resolve()
        local_path = (user_root / Path(*rel.parts)).resolve()
        if user_root != local_path and user_root not in local_path.parents:
            raise ValueError(f"Path escapes user sandbox root: {sandbox_path}")
        return local_path

    async def _ensure_container_connected(self) -> None:
        if self._container is None and self.external_id:
            await self._reconnect()
        if self._container is None:
            raise RuntimeError("Local docker sandbox is not connected")
