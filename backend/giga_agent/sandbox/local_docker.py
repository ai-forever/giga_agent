import asyncio
import mimetypes
import secrets
import shlex
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import aiofiles
import aiofiles.os
import docker
from docker.errors import NotFound
from docker.types import Ulimit
from pydantic import Field, PrivateAttr

from giga_agent.conf import (
    get_local_docker_max_active_sandboxes_from_env,
    get_settings,
)
from giga_agent.core.logging import get_logger
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    StreamResult,
)
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.registry import SandboxRegistry
from giga_agent.sandbox.manager.types import (
    LogOnlyOrphanAction,
    OrphanAction,
    RemoveExternalRuntimeAction,
    SetSandboxStatusAction,
    StopExternalRuntimeAction,
)

logger = get_logger(__name__)

JUPYTER_PORT = 8888
BUCKET_PREFIX = "/bucket/"
MANAGED_LABEL = "giga_agent.managed"
PROVIDER_TYPE_LABEL = "giga_agent.provider_type"
PROVIDER_ID_LABEL = "giga_agent.provider_id"
SANDBOX_ID_LABEL = "giga_agent.sandbox_id"
OWNER_ID_LABEL = "giga_agent.owner_id"


@SandboxRegistry.register("local_docker")
class LocalDockerSandbox(JupyterSandbox):
    image: str = Field(
        default="mikelarg/code-interpreter:0.0.5",
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

    def _docker_network(self) -> str | None:
        return get_settings().giga_agent_docker_network

    def _container_name(self) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for docker network mode")
        return f"giga-sandbox-{self.sandbox_id}"

    def _internal_base_url(self) -> str:
        return f"http://{self._container_name()}:{JUPYTER_PORT}"

    def _container_labels(self) -> dict[str, str]:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for docker labels")
        if self.provider_id is None:
            raise RuntimeError("provider_id is required for docker labels")
        if self.owner_id is None:
            raise RuntimeError("owner_id is required for docker labels")
        return {
            MANAGED_LABEL: "true",
            PROVIDER_TYPE_LABEL: "local_docker",
            PROVIDER_ID_LABEL: str(self.provider_id),
            SANDBOX_ID_LABEL: str(self.sandbox_id),
            OWNER_ID_LABEL: str(self.owner_id),
        }

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

    def model_post_init(self, __context: Any) -> None:
        self._client = docker.from_env()
        root_dir = get_settings().giga_agent_local_docker_files_path
        if root_dir is None:
            root_dir = ensure_giga_agent_dir() / "sandboxes"
        self._sandbox_root_dir = root_dir
        if self.jupyter_token:
            self._token = self.jupyter_token
        if self._docker_network() and not self.base_url and self.sandbox_id is not None:
            self.base_url = self._internal_base_url()

    @classmethod
    def has_limit_cls(cls) -> bool:
        return True

    def get_connection_settings(self) -> dict:
        settings: dict[str, Any] = {
            "external_id": self.external_id,
            "jupyter_token": self._token,
            "host_port": self.host_port,
        }
        return {k: v for k, v in settings.items() if v is not None}

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

        docker_network = self._docker_network()

        if docker_network:
            self.base_url = self._internal_base_url()
            container_name = self._container_name()
            try:
                existing = self._client.containers.get(container_name)
            except NotFound:
                existing = None

            if existing is not None:
                existing.reload()
                token = (
                    self.jupyter_token
                    or getattr(self, "_token", None)
                    or self._get_env_value(existing, "JUPYTER_TOKEN")
                )
                if token:
                    self._token = token
                    self.jupyter_token = token

                self._container = existing
                self.external_id = existing.id

                if await super().is_up():
                    return

                try:
                    existing.remove(force=True)
                except Exception as e:
                    raise RuntimeError(
                        f"Existing sandbox container '{container_name}' is unhealthy "
                        f"and could not be removed: {e}"
                    ) from e

        user_root = self._user_root_dir(self.owner_id)
        user_root.mkdir(parents=True, exist_ok=True)

        self._token = secrets.token_urlsafe(13)
        self.jupyter_token = self._token

        envs = {
            "JUPYTER_TOKEN": self._token,
            "JUPYTER_RUNTIME_DIR": "/tmp/jupyter_runtime",
            "IPYTHONDIR": "/tmp/ipython",
            "MATPLOTLIBRC": "/tmp/matplotlibrc",
        }
        settings = get_settings()
        bind_source = user_root
        if settings.giga_agent_host_project_path is not None:
            giga_dir = ensure_giga_agent_dir()
            try:
                rel_under_giga_dir = user_root.relative_to(giga_dir)
            except ValueError as e:
                raise ValueError(
                    "GIGA_AGENT_HOST_PROJECT_PATH is set, so local sandbox files must "
                    "be stored under `.giga_agent` to be mappable to the host project "
                    f"path. Got sandbox_path='{user_root}', giga_agent_dir='{giga_dir}'. "
                    "Use default location under `.giga_agent` or adjust "
                    "GIGA_AGENT_LOCAL_DOCKER_FILES_PATH to be inside `.giga_agent`."
                ) from e

            bind_source = (
                settings.giga_agent_host_project_path
                / ".giga_agent"
                / rel_under_giga_dir
            )
        run_kwargs: dict[str, Any] = {
            "command": "sleep infinity",
            "detach": True,
            "remove": True,
            "environment": envs,
            "labels": self._container_labels(),
            "volumes": {
                str(bind_source): {"bind": BUCKET_PREFIX.rstrip("/"), "mode": "rw"}
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
        if docker_network:
            run_kwargs["name"] = self._container_name()
            run_kwargs["network"] = docker_network
        else:
            run_kwargs["ports"] = {f"{JUPYTER_PORT}/tcp": None}
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
        if docker_network:
            self.host_port = None
            self.base_url = self._internal_base_url()
        else:
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

    @classmethod
    def _make_docker_client(cls) -> Any:
        return docker.from_env()

    @classmethod
    def _managed_container_filters(cls) -> dict[str, list[str]]:
        return {
            "label": [
                f"{MANAGED_LABEL}=true",
                f"{PROVIDER_TYPE_LABEL}=local_docker",
            ]
        }

    @classmethod
    def _parse_uuid_label(cls, labels: dict[str, str], key: str) -> uuid.UUID | None:
        raw = labels.get(key)
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None

    @classmethod
    def _container_is_running(cls, container: Any) -> bool:
        try:
            state = (container.attrs.get("State") or {})
            return bool(state.get("Running"))
        except Exception:
            return getattr(container, "status", None) == "running"

    @classmethod
    async def cleanup_orphans(
        cls,
        *,
        providers: list[Any],
        sandboxes: list[Any],
    ) -> list[OrphanAction]:
        sandbox_by_id = {sandbox.id: sandbox for sandbox in sandboxes}
        container_ids_by_sandbox_id: dict[uuid.UUID, set[str]] = {}
        actions: list[OrphanAction] = []
        client = None

        try:
            client = cls._make_docker_client()
            containers = client.containers.list(
                all=True,
                filters=cls._managed_container_filters(),
            )
            for container in containers:
                try:
                    container.reload()
                except Exception:
                    pass
                labels = getattr(container, "labels", None) or (
                    container.attrs.get("Config") or {}
                ).get("Labels", {}) or {}
                sandbox_id = cls._parse_uuid_label(labels, SANDBOX_ID_LABEL)
                provider_id = cls._parse_uuid_label(labels, PROVIDER_ID_LABEL)
                external_id = getattr(container, "id", "")

                if sandbox_id is None:
                    actions.append(
                        LogOnlyOrphanAction(
                            provider_type="local_docker",
                            provider_id=provider_id,
                            sandbox_id=None,
                            external_id=external_id or None,
                            level="warning",
                            reason="managed_local_docker_container_missing_sandbox_label",
                        )
                    )
                    continue

                container_ids_by_sandbox_id.setdefault(sandbox_id, set()).add(external_id)
                sandbox = sandbox_by_id.get(sandbox_id)
                if sandbox is None:
                    actions.append(
                        RemoveExternalRuntimeAction(
                            provider_type="local_docker",
                            provider_id=provider_id,
                            sandbox_id=sandbox_id,
                            external_id=external_id,
                            reason="managed_local_docker_container_without_sandbox_row",
                        )
                    )
                    continue

                if sandbox.external_id != external_id:
                    actions.append(
                        RemoveExternalRuntimeAction(
                            provider_type="local_docker",
                            provider_id=sandbox.provider_id,
                            sandbox_id=sandbox.id,
                            external_id=external_id,
                            reason="managed_local_docker_container_not_bound_to_sandbox_external_id",
                        )
                    )
                    continue

                if not cls._container_is_running(container):
                    actions.append(
                        SetSandboxStatusAction(
                            provider_type="local_docker",
                            provider_id=sandbox.provider_id,
                            sandbox_id=sandbox.id,
                            status=SandboxStatus.STOPPED,
                            reason="managed_local_docker_container_not_running",
                            clear_runtime_connection=True,
                        )
                    )
                    continue

                if sandbox.status in (
                    SandboxStatus.PENDING,
                    SandboxStatus.STOPPED,
                    SandboxStatus.ERROR,
                ):
                    actions.append(
                        StopExternalRuntimeAction(
                            provider_type="local_docker",
                            provider_id=sandbox.provider_id,
                            sandbox_id=sandbox.id,
                            external_id=external_id,
                            reason="managed_local_docker_container_running_for_non_running_sandbox",
                        )
                    )
                    actions.append(
                        SetSandboxStatusAction(
                            provider_type="local_docker",
                            provider_id=sandbox.provider_id,
                            sandbox_id=sandbox.id,
                            status=SandboxStatus.STOPPED,
                            reason="managed_local_docker_container_stopped_by_orphan_cleanup",
                            clear_runtime_connection=True,
                        )
                    )

            for sandbox in sandboxes:
                if sandbox.status not in (
                    SandboxStatus.RUNNING,
                    SandboxStatus.STARTING,
                ):
                    continue
                discovered_ids = container_ids_by_sandbox_id.get(sandbox.id, set())
                if sandbox.external_id and sandbox.external_id in discovered_ids:
                    continue
                actions.append(
                    SetSandboxStatusAction(
                        provider_type="local_docker",
                        provider_id=sandbox.provider_id,
                        sandbox_id=sandbox.id,
                        status=SandboxStatus.STOPPED,
                        reason="managed_local_docker_container_missing_for_active_sandbox",
                        clear_runtime_connection=True,
                    )
                )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        return actions

    @classmethod
    async def stop_external_runtime(cls, external_id: str) -> None:
        client = None
        try:
            client = cls._make_docker_client()
            try:
                container = client.containers.get(external_id)
            except NotFound:
                return
            try:
                container.stop(timeout=5)
            except NotFound:
                return
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    @classmethod
    async def remove_external_runtime(cls, external_id: str) -> None:
        client = None
        try:
            client = cls._make_docker_client()
            try:
                container = client.containers.get(external_id)
            except NotFound:
                return
            try:
                container.remove(force=True)
            except NotFound:
                return
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

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
        if (
            not self.base_url
            and self._docker_network()
            and self.sandbox_id is not None
        ):
            self.base_url = self._internal_base_url()
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
        async with aiofiles.open(target, "wb") as f:
            await f.write(content)
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

            async with aiofiles.open(local_path, "rb") as f:
                data = await f.read()
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
            try:
                await aiofiles.os.remove(local_path)
            except FileNotFoundError:
                pass
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
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
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
