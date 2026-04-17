import asyncio
import json
import mimetypes
import re
import secrets
import shlex
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Literal

import aiofiles
import aiofiles.os
import docker
from cashews import cache
from docker.errors import NotFound, DockerException
from docker.types import Ulimit
from pydantic import BaseModel, Field, PrivateAttr

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
from giga_agent.sandbox.mixins.code import ShellAwaitResult, ShellRunResult
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
_LOCAL_FILE_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MANAGED_LABEL = "giga_agent.managed"
PROVIDER_TYPE_LABEL = "giga_agent.provider_type"
PROVIDER_ID_LABEL = "giga_agent.provider_id"
SANDBOX_ID_LABEL = "giga_agent.sandbox_id"
OWNER_ID_LABEL = "giga_agent.owner_id"
_CONTAINER_HOME_DIR = PurePosixPath("/root")
_SHELL_POLL_INTERVAL_SEC = 0.2
_SHELL_STATUS_RUNNING = "running"
_SHELL_STATUS_COMPLETED = "completed"
_SHELL_STATUS_FAILED = "failed"
_CONTAINER_PYTHON_BIN = "python"


class LocalDockerShellMeta(BaseModel):
    shell_id: str
    exec_id: str | None = None
    command: str
    description: str | None = None
    cwd: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    ended_at: str | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    pid: int | None = None
    output_path: str
    exit_code_path: str | None = None
    output_size_bytes: int = 0
    last_delivered_offset: int = 0
    last_update_at: str

@SandboxRegistry.register("local_docker")
class LocalDockerSandbox(JupyterSandbox):
    image: str = Field(
        default_factory=lambda: get_settings().giga_agent_local_docker_image,
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

    def is_base_url_internal(self) -> bool:
        return self._docker_network() is not None

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
                try:
                    existing.reload()
                except NotFound:
                    existing = None

            if existing is not None:
                self._apply_container_connection(existing)
                if self._token and self._container_is_running(existing):
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
        self._apply_container_connection(self._container)

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
        except DockerException:
            pass
            return []
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
            container = self._client.containers.get(self.external_id)
            try:
                container.reload()
            except Exception:
                pass
            self._apply_container_connection(container)
        except NotFound:
            self._container = None

    def _apply_container_connection(self, container: Any) -> None:
        self._container = container
        container_id = getattr(container, "id", None)
        if isinstance(container_id, str) and container_id:
            self.external_id = container_id

        token = (
            self.jupyter_token
            or getattr(self, "_token", None)
            or self._get_env_value(container, "JUPYTER_TOKEN")
        )
        if token:
            self._token = token
            self.jupyter_token = token

        self._ensure_base_url()

    def _ensure_base_url(self) -> None:
        if self._docker_network() and self.sandbox_id is not None:
            self.host_port = None
            self.base_url = self._internal_base_url()
            return
        binding = None
        if self._container is not None:
            ports = (self._container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
            binding = ports.get(f"{JUPYTER_PORT}/tcp")
        if binding:
            self.host_port = int(binding[0]["HostPort"])
            self.base_url = f"http://localhost:{self.host_port}"
            return
        if not self.host_port:
            return
        self.base_url = f"http://localhost:{self.host_port}"

    async def _is_container_up(self) -> bool:
        try:
            await self._ensure_container_connected()
        except RuntimeError:
            return False
        assert self._container is not None
        try:
            self._container.reload()
        except NotFound:
            self._container = None
            return False
        except DockerException:
            return False
        self._apply_container_connection(self._container)
        return self._container_is_running(self._container)

    async def _is_jupyter_ready(self) -> bool:
        if not await self._is_container_up():
            return False
        if not self._token:
            return False
        self._ensure_base_url()
        if not self.base_url:
            return False
        return await super().is_up()

    def _jupyter_start_lock_key(self) -> str:
        identity = (
            str(self.sandbox_id)
            if self.sandbox_id is not None
            else self.external_id
            or (str(self.owner_id) if self.owner_id is not None else None)
        )
        if not identity:
            raise RuntimeError("sandbox identity is required for jupyter startup lock")
        return f"sandbox:jupyter-start:{identity}"

    async def _start_jupyter_server(self) -> None:
        await self._ensure_container_connected()
        assert self._container is not None
        cmd = (
            f"jupyter server --ip=0.0.0.0 --port={JUPYTER_PORT} --allow-root "
            '--ServerApp.token="${JUPYTER_TOKEN}" > /dev/null 2>&1 &'
        )
        logger.info(
            "Starting Jupyter inside local sandbox container %s",
            getattr(self._container, "id", "")[:12],
        )
        exit_code, output = await self._run_exec_in_container(cmd=["sh", "-lc", cmd])
        if exit_code != 0:
            raise RuntimeError(
                "Failed to start Jupyter server: "
                + self._decode_container_output(output).strip()
            )

    async def _wait_for_jupyter_ready(self) -> None:
        start = time.time()
        while True:
            if await self._is_jupyter_ready():
                return
            if time.time() - start > self.startup_timeout_sec:
                raise TimeoutError(
                    f"Jupyter did not start within {self.startup_timeout_sec} seconds"
                )
            await asyncio.sleep(1)

    async def _ensure_jupyter_ready(self) -> bool:
        if await self._is_jupyter_ready():
            return False

        lock_timeout = float(max(self.startup_timeout_sec + 5, 5))
        try:
            async with asyncio.timeout(lock_timeout):
                async with cache.lock(
                    self._jupyter_start_lock_key(),
                    expire=lock_timeout + 5,
                    wait=True,
                    check_interval=0.05,
                ):
                    if await self._is_jupyter_ready():
                        return False
                    if not await self._is_container_up():
                        raise RuntimeError(
                            "Local docker sandbox container is not running"
                        )
                    await self._start_jupyter_server()
                    await self._wait_for_jupyter_ready()
                    return True
        except TimeoutError as exc:
            raise TimeoutError(
                "Timed out while waiting to start Jupyter in local docker sandbox"
            ) from exc

    async def is_up(self) -> bool:
        return await self._is_container_up()

    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        envs: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        jupyter_started = await self._ensure_jupyter_ready()
        effective_kernel_id = kernel_id
        if jupyter_started:
            logger.info(
                "Jupyter was started lazily for sandbox %s; resetting kernel state",
                self.sandbox_id,
            )
            self._kernel_id = None
            effective_kernel_id = None

        async for chunk in super().run_code(
            code,
            kernel_id=effective_kernel_id,
            allow_stdin=allow_stdin,
            envs=envs,
            **kwargs,
        ):
            yield chunk

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

    def _decode_container_output(self, data: bytes) -> str:
        return data.decode("utf-8", errors="replace")

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        rel_path = self._uniquify_bucket_rel_path(owner_id=owner_id, file_name=file_name)
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

    def _uniquify_bucket_rel_path(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
    ) -> PurePosixPath:
        path = self._validate_relative_file_name(file_name)
        plotly_json_suffix = ".plotly.json"
        name = path.name
        if name.lower().endswith(plotly_json_suffix) and len(name) > len(
            plotly_json_suffix
        ):
            suffix_start = len(name) - len(plotly_json_suffix)
            stem = name[:suffix_start]
            suffix = name[suffix_start:]
        else:
            stem = path.stem or path.name
            suffix = path.suffix

        parent = path.parent
        parent_parts = (
            []
            if str(parent) in {"", "."}
            else [p for p in parent.parts if p not in {"", "."}]
        )
        user_root = self._user_root_dir(owner_id)
        for _ in range(10):
            suffix_id = self._random_key_suffix()
            candidate_name = (
                f"{stem}--{suffix_id}{suffix}" if suffix else f"{stem}--{suffix_id}"
            )
            rel_path = (
                PurePosixPath(*parent_parts, candidate_name)
                if parent_parts
                else PurePosixPath(candidate_name)
            )
            target = user_root / Path(*rel_path.parts)
            if not target.exists():
                return rel_path

        raise RuntimeError(
            "Failed to generate unique local upload file name after retries"
        )

    def _random_key_suffix(self) -> str:
        return "".join(secrets.choice(_LOCAL_FILE_SUFFIX_ALPHABET) for _ in range(8))

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
