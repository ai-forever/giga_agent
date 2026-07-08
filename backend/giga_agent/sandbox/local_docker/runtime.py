"""LocalDockerSandbox — Docker-backed Jupyter sandbox runtime."""

import asyncio
import os
import secrets
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import docker
from cashews import cache
from docker.errors import DockerException, NotFound
from docker.types import Ulimit
from langchain_core.runnables import RunnableConfig
from pydantic import Field, PrivateAttr

from giga_agent.conf import (
    get_local_docker_max_active_sandboxes_from_env,
    get_settings,
)
from giga_agent.core.logging import get_logger
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.access import revoke_sandbox_access_tokens
from giga_agent.sandbox.api_backed import APIBackedSandbox
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.local_docker.constants import (
    BUCKET_PREFIX,
    MANAGED_LABEL,
    OWNER_ID_LABEL,
    PROVIDER_ID_LABEL,
    PROVIDER_TYPE_LABEL,
    PROXY_LABEL,
    SANDBOX_ID_LABEL,
)
from giga_agent.sandbox.local_docker.container import ContainerMixin
from giga_agent.sandbox.local_docker.files import FilesMixin
from giga_agent.sandbox.local_docker.proxy import PortProxyMixin
from giga_agent.sandbox.manager.types import (
    LogOnlyOrphanAction,
    OrphanAction,
    RemoveExternalRuntimeAction,
    SetSandboxStatusAction,
    StopExternalRuntimeAction,
)
from giga_agent.sandbox.registry import SandboxRegistry

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort

logger = get_logger(__name__)


@SandboxRegistry.register("local_docker")
class LocalDockerSandbox(
    APIBackedSandbox, ContainerMixin, FilesMixin, PortProxyMixin, JupyterSandbox,
):
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
    not_remove: bool = Field(
        default=False,
        description=(
            "Do not auto-remove the container after stop; reuse the same "
            "container on next up(). If Jupyter cannot be brought up in the "
            "reused container, it is removed and a new one is created."
        ),
    )

    external_id: Optional[str] = Field(
        default=None,
        description="Docker container ID",
    )
    host_port: Optional[int] = Field(
        default=None,
        description="Mapped host port for the SandboxAPI server",
    )

    # Наследуется от JupyterSandbox как required — здесь не используется
    # (кернелы/шелл/файлы идут через SandboxAPI), держим пустым по умолчанию.
    base_url: str = Field(default="", description="unused (legacy)")

    _runtime_fields = APIBackedSandbox._runtime_fields | {
        "host_port",
        "owner_id",
    }

    _client: Any = PrivateAttr(default=None)
    _container: Any = PrivateAttr(default=None)
    _sandbox_root_dir: Path = PrivateAttr(default_factory=Path)

    # ------------------------------------------------------------------
    # Docker network / naming
    # ------------------------------------------------------------------

    def _docker_network(self) -> str | None:
        return get_settings().giga_agent_docker_network

    def _container_name(self) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for docker network mode")
        return f"giga-sandbox-{self.sandbox_id}"

    def _container_hex_alias(self) -> str:
        if self.sandbox_id is None:
            raise RuntimeError("sandbox_id is required for docker network alias")
        return f"giga-sandbox-{self.sandbox_id.hex}"

    def _ensure_hex_alias(self, network_name: str) -> None:
        """Add the hex32 DNS alias to the sandbox container in the given network.

        Idempotent: noop when the alias is already present. If the container is
        already attached to the network without the alias, the endpoint is
        re-created (disconnect + connect with the desired aliases) — Docker has
        no API to mutate aliases of an existing endpoint.
        """
        if self._container is None:
            return
        if not get_settings().giga_agent_public_base_domain:
            return
        alias = self._container_hex_alias()
        try:
            self._container.reload()
        except NotFound:
            return
        networks = (
            (self._container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        )
        net_info = networks.get(network_name) or {}
        existing_aliases = net_info.get("Aliases") or []
        if alias in existing_aliases:
            return
        try:
            network = self._client.networks.get(network_name)
        except NotFound:
            return

        is_attached = network_name in networks
        try:
            if is_attached:
                try:
                    network.disconnect(self._container, force=True)
                except DockerException:
                    logger.warning(
                        "Failed to detach container %s from network %s "
                        "before attaching hex alias",
                        getattr(self._container, "id", "")[:12],
                        network_name,
                        exc_info=True,
                    )
                    return
            network.connect(self._container, aliases=[alias])
        except DockerException:
            logger.warning(
                "Failed to attach hex alias %s to container %s",
                alias,
                getattr(self._container, "id", "")[:12],
                exc_info=True,
            )
            return
        try:
            self._container.reload()
        except DockerException:
            pass

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

    # ------------------------------------------------------------------
    # init / connection settings
    # ------------------------------------------------------------------

    def model_post_init(self, __context: Any) -> None:
        self._client = docker.from_env()
        root_dir = get_settings().giga_agent_local_docker_files_path
        if root_dir is None:
            root_dir = ensure_giga_agent_dir() / "sandboxes"
        self._sandbox_root_dir = root_dir

    @classmethod
    def has_limit_cls(cls) -> bool:
        return True

    def get_connection_settings(self) -> dict:
        settings: dict[str, Any] = {
            "external_id": self.external_id,
            "host_port": self.host_port,
            "api_base_url": self.api_base_url,
            "api_token": self.api_token,
        }
        return {k: v for k, v in settings.items() if v is not None}

    def preserve_runtime_state_on_stop(self) -> bool:
        return self.not_remove

    def current_workdir(self) -> str | None:
        return "/root"

    @staticmethod
    def get_tools() -> list:
        settings = get_settings()
        if (
            settings.giga_agent_docker_network is not None
            and not settings.giga_agent_public_base_domain
            and not settings.giga_agent_publish_cloudflare_tunnel
        ):
            return []
        from giga_agent.sandbox.local_docker.tools import open_port

        return [open_port]

    def _image_version(self) -> tuple[int, ...] | None:
        """Return the image tag as a tuple of ints (e.g. (0, 0, 6))."""
        _, _, tag = (self.image or "").rpartition(":")
        if not tag:
            return None
        try:
            return tuple(int(part) for part in tag.split("."))
        except ValueError:
            return None

    def get_prompt(
        self,
        user: "UserShort | None" = None,
        agent: "BaseAgent | None" = None,
        state: "AgentState | None" = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str:
        _ = user, agent, state, config, kwargs

        settings = get_settings()
        base_domain = settings.giga_agent_public_base_domain
        tunnel_enabled = settings.giga_agent_publish_cloudflare_tunnel
        docker_network = self._docker_network()
        tunnel_active = tunnel_enabled and not base_domain

        lines: list[str] = [
            "",
            "=== Sandbox runtime (Docker) ===",
            "Workdir: /root. "
            "Эфемерно: /tmp, /run.",
            "",
            "=== Что использовать для типичных задач ===",
            "- Установить Python-пакет → `uv pip install --no-cache <pkg>` "
            "(в разы быстрее pip, без venv — UV_SYSTEM_PYTHON уже выставлен).",
            "- Установить npm-пакет → `bun add <pkg>` (быстрее всего) "
            "или `pnpm add <pkg>`. NPM работает, но медленнее.",
            "- Запустить TypeScript-файл → `bun run script.ts` "
            "(без отдельной компиляции).",
            "- Запустить пакет одноразово (аналог npx) → `bunx <cmd> [args]` "
            "(в 5-10× быстрее npx за счёт нативного рантайма и общего кэша "
            "`~/.bun/install/cache`). Если пакет упал с ошибкой про "
            "несовместимость с Node — fallback `npx <cmd>`. Принудительно "
            "запустить через bun-runtime (без node-shim) — `bunx --bun <cmd>`.",
            "- Искать по коду → `rg 'pattern' path/` (НЕ `grep -r`).",
            "- Искать файлы → `fd -e py -t f` (НЕ `find`).",
            "- Парсить JSON в shell → `jq`.",
            "- Скачать страницу → `curl -fsSL URL`. JS-рендеринг → "
            "`/usr/local/bin/chromium-headless --headless URL > out.html` "
            "(PUPPETEER_EXECUTABLE_PATH уже указывает на этот бинарь, "
            "PUPPETEER_SKIP_DOWNLOAD=true — pyppeteer/playwright не качают свой).",
            "- Видео/аудио → `ffmpeg`.",
            "- Клонировать репозиторий → `git clone <url>`.",
            "- Сжатие → `zip`/`unzip`/`xz`",
            "",
            "Что НЕ работает: GUI/X-сервер, "
            "(пакеты только через uv/pnpm/bun)"
        ]

        lines.extend([
            "",
            "=== Запуск долгоиграющего сервера ===",
            "1. Запустите сервер в фоне на 0.0.0.0:<port>, "
            "НЕ на 127.0.0.1 (иначе извне не достучитесь)"
        ])

        if base_domain:
            lines.extend([
                "2. Дёрните `open_port(<port>)` — вернётся HTTPS-URL вида "
                f"`https://<port>-sandbox-<id>.{base_domain}/`.",
                "",
                "ОТДАВАЙ ССЫЛКУ РОВНО ТАК, КАК ВЕРНУЛ `open_port` — НЕ дописывай "
                "и не выдумывай query-параметры (никаких `?__sbx=...`). "
                "Хозяин песочницы открывает её по своей сессии, без токена. "
                "Если ссылка уходит туда, где нет сессии (например, в Telegram), "
                "временный токен доступа (~10 часов, только к этому порту этой "
                "песочницы, не к аккаунту) подставляется автоматически.",
                "",
                "⚠ ВНУТРИ ПРИЛОЖЕНИЯ ОТКЛЮЧИТЕ host/CORS-проверки, иначе "
                f"фреймворк отдаст 400/403 (приходящий Host = "
                f"`<port>-sandbox-<hex>.{base_domain}`):",
                "  • Django: ALLOWED_HOSTS=['*']; USE_X_FORWARDED_HOST=True; "
                "SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https')",
                "  • FastAPI/Starlette: убрать TrustedHostMiddleware либо "
                "allowed_hosts=['*']; uvicorn — с --proxy-headers "
                "--forwarded-allow-ips='*'",
                "  • Flask: werkzeug.middleware.proxy_fix.ProxyFix(app, "
                "x_proto=1, x_host=1)",
                "  • Streamlit: --server.enableCORS=false "
                "--server.enableXsrfProtection=false --server.headless=true "
                "--server.address=0.0.0.0",
                "  • Gradio: launch(server_name='0.0.0.0', server_port=<port>)",
                "  • Next.js/Vite: --host 0.0.0.0; для Vite в "
                f"vite.config — server.allowedHosts: ['.{base_domain}']",
            ])
        elif tunnel_active:
            lines.extend([
                "2. Дёрните `open_port(<port>)` — вернётся публичный HTTPS-URL "
                "вида `https://<random>.trycloudflare.com` (Cloudflare quick "
                "tunnel).",
                "",
                "⚠ ССЫЛКА ПУБЛИЧНАЯ: открыть может КТО УГОДНО, у кого есть URL "
                "(без авторизации). Не открывайте так ничего с приватными "
                "данными.",
                "",
                "⚠ ВНУТРИ ПРИЛОЖЕНИЯ ОТКЛЮЧИТЕ host/CORS-проверки, иначе "
                "фреймворк отдаст 400/403 (приходящий Host = "
                "`<random>.trycloudflare.com`):",
                "  • Django: ALLOWED_HOSTS=['*']; USE_X_FORWARDED_HOST=True; "
                "SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https')",
                "  • FastAPI/Starlette: убрать TrustedHostMiddleware либо "
                "allowed_hosts=['*']; uvicorn — с --proxy-headers "
                "--forwarded-allow-ips='*'",
                "  • Flask: werkzeug.middleware.proxy_fix.ProxyFix(app, "
                "x_proto=1, x_host=1)",
                "  • Streamlit: --server.enableCORS=false "
                "--server.enableXsrfProtection=false --server.headless=true "
                "--server.address=0.0.0.0",
                "  • Gradio: launch(server_name='0.0.0.0', server_port=<port>)",
                "  • Next.js/Vite: --host 0.0.0.0; для Vite в "
                "vite.config — server.allowedHosts: ['.trycloudflare.com']",
            ])
        elif docker_network is None:
            lines.append(
                "2. `open_port(<port>)` → `http://localhost:<port>` "
                "(локальный dev)."
            )

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # lifecycle: up / stop / is_up
    # ------------------------------------------------------------------

    async def up(self) -> None:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required for local_docker runtime")

        docker_network = self._docker_network()

        existing = self._find_reusable_container(docker_network)
        if existing is not None:
            if await self._try_reuse_container(existing):
                return
            try:
                existing.remove(force=True)
            except Exception as e:
                raise RuntimeError(
                    "Existing sandbox container is unhealthy "
                    f"and could not be removed: {e}"
                ) from e

        user_root = self._user_root_dir(self.owner_id)
        user_root.mkdir(parents=True, exist_ok=True)

        settings = get_settings()
        api_port = settings.giga_agent_sandbox_api_port
        self.api_token = secrets.token_urlsafe(24)

        envs = {
            "SANDBOX_API_TOKEN": self.api_token,
            "SANDBOX_API_PORT": str(api_port),
            "SANDBOX_WORKDIR": self.current_workdir() or "/root",
            "MATPLOTLIBRC": "/tmp/matplotlibrc",
        }
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
        bucket_mount = BUCKET_PREFIX.rstrip("/")
        run_kwargs: dict[str, Any] = {
            # sandbox-server как главный процесс (supervisor авто-рестартит его
            # при падении; совместимо с docker --rm, в отличие от restart_policy)
            "command": ["sandbox-server-supervised"],
            "detach": True,
            "remove": not self.not_remove,
            "environment": envs,
            "labels": self._container_labels(),
            "volumes": {
                str(bind_source): {"bind": bucket_mount, "mode": "rw"}
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
            run_kwargs["ports"] = {f"{api_port}/tcp": None}
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
            self._ensure_hex_alias(docker_network)
            self._container.reload()
        self._apply_container_connection(self._container)
        await self._ensure_api_server_ready()

    async def _ensure_api_server_ready(self) -> None:
        ok = await self._wait_for_sandbox_api(
            get_settings().giga_agent_sandbox_api_startup_timeout_sec
        )
        if not ok:
            raise RuntimeError(
                "SandboxAPI server did not become healthy inside the container. "
                "Убедись, что образ содержит sandbox-server "
                f"(image={self.image}); обнови GIGA_AGENT_LOCAL_DOCKER_IMAGE "
                "до версии с сервером."
            )

    def _find_reusable_container(self, docker_network: str | None) -> Any:
        if docker_network:
            try:
                existing = self._client.containers.get(self._container_name())
            except NotFound:
                return None
        elif self.not_remove and self.external_id:
            try:
                existing = self._client.containers.get(self.external_id)
            except NotFound:
                return None
        else:
            return None

        try:
            existing.reload()
        except NotFound:
            return None
        return existing

    async def _try_reuse_container(self, container: Any) -> bool:
        self._apply_container_connection(container)

        if not self._container_is_running(container):
            if not self.not_remove:
                return False
            try:
                container.start()
                container.reload()
            except DockerException:
                logger.warning(
                    "Failed to start existing sandbox container %s",
                    getattr(container, "id", "")[:12],
                    exc_info=True,
                )
                return False
            self._apply_container_connection(container)
            if not self._container_is_running(container):
                return False
            self._kernel_id = None

        # api_token восстанавливается из env контейнера в _apply_container_connection
        if not self.api_token:
            return False

        try:
            await self._ensure_api_server_ready()
        except Exception:
            logger.warning(
                "SandboxAPI failed to become ready in reused sandbox container %s; "
                "recreating",
                getattr(container, "id", "")[:12],
                exc_info=True,
            )
            return False
        return True

    async def stop(self) -> None:
        if self.sandbox_id is not None:
            await revoke_sandbox_access_tokens(self.sandbox_id.hex)
        self._stop_proxy_containers()
        self._remove_proxy_network()

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

    async def is_up(self) -> bool:
        return await self._is_container_up()

    # ------------------------------------------------------------------
    # reconnect / connection state
    # ------------------------------------------------------------------

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

        token = self.api_token or self._get_env_value(container, "SANDBOX_API_TOKEN")
        if token:
            self.api_token = token

        docker_network = self._docker_network()
        if docker_network:
            self._ensure_hex_alias(docker_network)

        self._ensure_api_base_url()

    def _ensure_api_base_url(self) -> None:
        port = get_settings().giga_agent_sandbox_api_port
        if self._docker_network() and self.sandbox_id is not None:
            self.host_port = None
            self.api_base_url = f"http://{self._container_name()}:{port}"
            return
        binding = None
        if self._container is not None:
            ports = (self._container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
            binding = ports.get(f"{port}/tcp")
        if binding:
            self.host_port = int(binding[0]["HostPort"])
            self.api_base_url = f"http://localhost:{self.host_port}"
            return
        if self.host_port:
            self.api_base_url = f"http://localhost:{self.host_port}"

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

    # ------------------------------------------------------------------
    # orphan cleanup (class-level)
    # ------------------------------------------------------------------

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

                if labels.get(PROXY_LABEL) == "true":
                    continue

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
                    cls._cleanup_proxy_for_sandbox(client, sandbox_id)
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
                    cls._cleanup_proxy_for_sandbox(client, sandbox.id)
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
                    cls._cleanup_proxy_for_sandbox(client, sandbox.id)
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
                cls._cleanup_proxy_for_sandbox(client, sandbox.id)
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

            cls._cleanup_orphan_proxy_containers(client, sandbox_by_id)
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
    def _cleanup_orphan_proxy_containers(
        cls,
        client: Any,
        sandbox_by_id: dict[uuid.UUID, Any],
    ) -> None:
        """Remove proxy containers whose sandbox no longer exists or is stopped."""
        try:
            proxies = client.containers.list(
                all=True,
                filters={
                    "label": [
                        f"{MANAGED_LABEL}=true",
                        f"{PROXY_LABEL}=true",
                    ]
                },
            )
        except DockerException:
            return

        orphan_sandbox_ids: set[uuid.UUID] = set()
        for proxy in proxies:
            labels = getattr(proxy, "labels", None) or {}
            sandbox_id = cls._parse_uuid_label(labels, SANDBOX_ID_LABEL)
            if sandbox_id is None:
                try:
                    proxy.remove(force=True)
                except Exception:
                    pass
                continue
            sandbox = sandbox_by_id.get(sandbox_id)
            if sandbox is None or sandbox.status in (
                SandboxStatus.PENDING,
                SandboxStatus.STOPPED,
                SandboxStatus.ERROR,
            ):
                orphan_sandbox_ids.add(sandbox_id)

        for sid in orphan_sandbox_ids:
            cls._cleanup_proxy_for_sandbox(client, sid)

    @classmethod
    async def stop_external_runtime(cls, external_id: str) -> None:
        client = None
        try:
            client = cls._make_docker_client()
            try:
                container = client.containers.get(external_id)
            except NotFound:
                return
            sandbox_id = cls._parse_uuid_label(
                getattr(container, "labels", None) or {}, SANDBOX_ID_LABEL,
            )
            if sandbox_id is not None:
                cls._cleanup_proxy_for_sandbox(client, sandbox_id)
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
            sandbox_id = cls._parse_uuid_label(
                getattr(container, "labels", None) or {}, SANDBOX_ID_LABEL,
            )
            if sandbox_id is not None:
                cls._cleanup_proxy_for_sandbox(client, sandbox_id)
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

    # ------------------------------------------------------------------
    # Skill file operations
    # ------------------------------------------------------------------

    _SKILL_CACHE_TTL = int(os.getenv("GIGA_AGENT_SKILL_CACHE_TTL", "300"))
    _SKILL_CACHE_ENABLED = os.getenv("GIGA_AGENT_SKILL_CACHE_ENABLED", "true").lower() != "false"

    def _skill_dir(self, owner_id: uuid.UUID, skill_name: str) -> Path:
        return self._user_root_dir(owner_id) / ".skills" / skill_name

    def _skill_cache_key(self, owner_id: uuid.UUID, skill_name: str, rel: str) -> str:
        return f"skill:file:{owner_id}:{skill_name}:{rel}"

    def _skill_list_cache_key(self, owner_id: uuid.UUID, skill_name: str) -> str:
        return f"skill:list:{owner_id}:{skill_name}"

    async def install_skill_files(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        source_dir: str | Path,
    ) -> str:
        source = Path(source_dir)
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory not found: {source}")
        dest = self._skill_dir(owner_id, skill_name)
        if dest.exists():
            shutil.rmtree(dest)
        await asyncio.to_thread(shutil.copytree, source, dest)
        await self._invalidate_skill_cache(owner_id, skill_name)
        return f".skills/{skill_name}"

    async def read_skill_file(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        skill_name = storage_path.split("/")[-1]
        cache_key = self._skill_cache_key(owner_id, skill_name, relative_path)

        if self._SKILL_CACHE_ENABLED:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        file_path = self._skill_dir(owner_id, skill_name) / relative_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Skill file not found: {relative_path}")

        import aiofiles

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()

        if self._SKILL_CACHE_ENABLED and self._SKILL_CACHE_TTL > 0:
            await cache.set(cache_key, content, expire=self._SKILL_CACHE_TTL)

        return content

    async def list_skill_files(
        self, owner_id: uuid.UUID, storage_path: str
    ) -> list[str]:
        skill_name = storage_path.split("/")[-1]
        cache_key = self._skill_list_cache_key(owner_id, skill_name)

        if self._SKILL_CACHE_ENABLED:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        skill_dir = self._skill_dir(owner_id, skill_name)
        if not skill_dir.is_dir():
            return []

        result: list[str] = []
        for root, _dirs, files in os.walk(skill_dir):
            for fname in files:
                full = Path(root) / fname
                result.append(str(full.relative_to(skill_dir)))
        result.sort()

        if self._SKILL_CACHE_ENABLED and self._SKILL_CACHE_TTL > 0:
            await cache.set(cache_key, result, expire=self._SKILL_CACHE_TTL)

        return result

    async def remove_skill_files(
        self, owner_id: uuid.UUID, storage_path: str
    ) -> None:
        skill_name = storage_path.split("/")[-1]
        skill_dir = self._skill_dir(owner_id, skill_name)
        if skill_dir.is_dir():
            await asyncio.to_thread(shutil.rmtree, skill_dir)
        await self._invalidate_skill_cache(owner_id, skill_name)

    def get_skill_sandbox_path(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        return f"{BUCKET_PREFIX}{storage_path}/{relative_path}"

    async def _invalidate_skill_cache(self, owner_id: uuid.UUID, skill_name: str) -> None:
        if not self._SKILL_CACHE_ENABLED:
            return
        pattern = f"skill:*:{owner_id}:{skill_name}*"
        try:
            await cache.delete_match(pattern)
        except Exception:
            pass
