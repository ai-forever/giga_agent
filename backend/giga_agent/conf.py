from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    giga_agent_prefix_api: str = Field("/agent", alias="GIGA_AGENT_PREFIX_API")
    giga_agent_base_url: str | None = Field(None, alias="GIGA_AGENT_BASE_URL")
    giga_agent_frontend_dir: str | None = Field(None, alias="GIGA_AGENT_FRONTEND_DIR")
    giga_agent_ui: bool = Field(True, alias="GIGA_AGENT_UI")
    giga_agent_ui_prefix: Optional[str] = Field(None, alias="GIGA_AGENT_UI_PREFIX")

    giga_agent_runtime: str = Field("local", alias="GIGA_AGENT_RUNTIME")
    giga_agent_runtime_local: bool = Field(False, alias="GIGA_AGENT_RUNTIME_LOCAL")
    giga_agent_cli_cwd: str | None = Field(None, alias="GIGA_AGENT_CLI_CWD")
    giga_agent_cli_config: str | None = Field(None, alias="GIGA_AGENT_CLI_CONFIG")
    giga_agent_cli_no_sandbox: bool = Field(
        False, alias="GIGA_AGENT_CLI_NO_SANDBOX"
    )
    giga_agent_database_url: str | None = Field(None, alias="GIGA_AGENT_DATABASE_URL")
    giga_agent_project_root: Path = Field(
        default_factory=lambda: Path.cwd() / ".giga_agent",
        alias="GIGA_AGENT_PROJECT_ROOT",
    )
    giga_agent_host_project_path: Path | None = Field(
        None,
        alias="GIGA_AGENT_HOST_PROJECT_PATH",
        validation_alias=AliasChoices(
            "GIGA_AGENT_HOST_PROJECT_PATH",
            "GIGA_AGENT_HOSt_PROJECT_PATH",
        ),
    )
    giga_agent_docker_network: str | None = Field(
        None,
        alias="GIGA_AGENT_DOCKER_NETWORK",
    )
    giga_agent_public_base_domain: str | None = Field(
        None,
        alias="GIGA_AGENT_PUBLIC_BASE_DOMAIN",
    )
    giga_agent_publish_cloudflare_tunnel: bool = Field(
        False,
        alias="GIGA_AGENT_PUBLISH_CLOUDFLARE_TUNNEL",
    )
    # Cross-domain sandbox port mode: when set (e.g. "gigapp.ru"), ``open_port``
    # returns a same-origin link on the app domain (built from
    # ``GIGA_AGENT_BASE_URL``) that redirects to
    # ``https://{port}-sandbox-{hex}.{this}/?__sbx=<token>``. Presence enables
    # the mode.
    giga_agent_sandbox_port_redirect_base: str | None = Field(
        None,
        alias="GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE",
    )
    # Domain for the app session cookie in cross-domain mode. Empty -> host-only
    # cookie bound to the app host (correct default when app and sandboxes live
    # on different domains).
    giga_agent_app_cookie_domain: str | None = Field(
        None,
        alias="GIGA_AGENT_APP_COOKIE_DOMAIN",
    )
    giga_agent_host: str | None = Field(None, alias="GIGA_AGENT_HOST")
    giga_agent_port: str | None = Field(None, alias="GIGA_AGENT_PORT")

    # OAuth client credentials for native integration providers (optional).
    yandex_oauth_client_id: str | None = Field(None, alias="YANDEX_OAUTH_CLIENT_ID")
    yandex_oauth_client_secret: str | None = Field(
        None, alias="YANDEX_OAUTH_CLIENT_SECRET"
    )
    yandex_oauth_scope: str = Field(
        "cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info",
        alias="YANDEX_OAUTH_SCOPE",
    )
    google_oauth_client_id: str | None = Field(None, alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str | None = Field(
        None, alias="GOOGLE_OAUTH_CLIENT_SECRET"
    )
    google_oauth_scope: str = Field(
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.compose",
        alias="GOOGLE_OAUTH_SCOPE",
    )

    giga_agent_alembic_fileconfig: bool = Field(
        False, alias="GIGA_AGENT_ALEMBIC_FILECONFIG"
    )
    giga_agent_skip_startup_migrations: bool = Field(
        False, alias="GIGA_AGENT_SKIP_STARTUP_MIGRATIONS"
    )
    giga_agent_skip_onboarding: bool = Field(False, alias="GIGA_AGENT_SKIP_ONBOARDING")
    giga_agent_experimental_mode: bool = Field(
        False, alias="GIGA_AGENT_EXPERIMENTAL_MODE"
    )
    giga_agent_experimental_rewrite_model: str = Field(
        "GigaChat-3-Ultra", alias="GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL"
    )
    giga_agent_experimental_status_model: str = Field(
        "GigaChat-3-Pro", alias="GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL"
    )
    giga_agent_stt_runtime: str = Field("salute", alias="GIGA_AGENT_STT_RUNTIME")
    giga_agent_startup_migrations_lock_key: str = Field(
        "startup:migrations:lock",
        alias="GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_KEY",
    )
    giga_agent_startup_migrations_lock_ttl_sec: int = Field(
        1800,
        alias="GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_TTL_SEC",
    )
    giga_agent_log_format: str | None = Field(None, alias="GIGA_AGENT_LOG_FORMAT")
    giga_agent_log_json: bool = Field(False, alias="GIGA_AGENT_LOG_JSON")
    giga_agent_gigachat_from_env: bool = Field(
        False, alias="GIGA_AGENT_GIGACHAT_FROM_ENV"
    )
    giga_agent_gigachat_skip_cache_token: bool = Field(
        False, alias="GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN"
    )

    giga_agent_auth_algorithm: str = Field("HS256", alias="GIGA_AGENT_AUTH_ALGORITHM")
    giga_agent_admin_email: str = Field(
        "admin@example.com",
        alias="GIGA_AGENT_ADMIN_EMAIL",
    )
    giga_agent_admin_password: str = Field(
        "giga_agent_admin", alias="GIGA_AGENT_ADMIN_PASSWORD"
    )
    giga_agent_secret_key: Optional[str] = Field(
        None,
        alias="GIGA_AGENT_SECRET_KEY",
    )

    # Учётные данные одного зарегистрированного приложения Яндекс OAuth.
    # Общие для всех yandex-модулей (Диск/Трекер): scope запрашивается под модуль
    # в момент авторизации. Если не заданы — кнопка «Подключить Яндекс» неактивна,
    # модули продолжают работать на ручных токенах.
    giga_agent_yandex_oauth_client_id: str | None = Field(
        None, alias="YANDEX_OAUTH_CLIENT_ID"
    )
    giga_agent_yandex_oauth_client_secret: str | None = Field(
        None, alias="YANDEX_OAUTH_CLIENT_SECRET"
    )
    # Явный redirect_uri для server-callback. Если пуст — собирается из
    # GIGA_AGENT_BASE_URL + префикса API (см. yandex_oauth.service.redirect_uri).
    giga_agent_yandex_oauth_redirect_uri: str | None = Field(
        None, alias="YANDEX_OAUTH_REDIRECT_URI"
    )
    # Отдельное приложение под Яндекс.Почту (Яндекс требует отдельное под
    # mail-scope). Если не заданы — почта использует общие creds выше.
    # Redirect у mail-приложения — тот же общий callback.
    giga_agent_yandex_mail_client_id: str | None = Field(
        None, alias="YANDEX_OAUTH_CLIENT_ID_YANDEX_MAIL"
    )
    giga_agent_yandex_mail_client_secret: str | None = Field(
        None, alias="YANDEX_OAUTH_CLIENT_SECRET_YANDEX_MAIL"
    )

    giga_agent_langgraph_api_url: str | None = Field(
        None, alias="GIGA_AGENT_LANGGRAPH_API_URL"
    )

    # Максимум одновременных активных (busy) тредов графа giga_agent на
    # пользователя; <= 0 — лимит выключен.
    giga_agent_max_active_threads_per_user: int = Field(
        5, alias="GIGA_AGENT_MAX_ACTIVE_THREADS_PER_USER"
    )

    giga_agent_langgraph_dev_uvicorn_app: str | None = Field(
        None, alias="GIGA_AGENT_LANGGRAPH_DEV_UVICORN_APP"
    )
    giga_agent_langgraph_dev_host: str = Field(
        "127.0.0.1", alias="GIGA_AGENT_LANGGRAPH_DEV_HOST"
    )
    giga_agent_langgraph_dev_port: int = Field(
        9090, alias="GIGA_AGENT_LANGGRAPH_DEV_PORT"
    )
    giga_agent_langgraph_dev_reload: bool = Field(
        True, alias="GIGA_AGENT_LANGGRAPH_DEV_RELOAD"
    )
    giga_agent_log_level: str = Field("INFO", alias="GIGA_AGENT_LOG_LEVEL")
    giga_agent_langgraph_dev_graphs_json: str = Field(
        "{}", alias="GIGA_AGENT_LANGGRAPH_DEV_GRAPHS_JSON"
    )
    giga_agent_langgraph_dev_auth_path: str = Field(
        "", alias="GIGA_AGENT_LANGGRAPH_DEV_AUTH_PATH"
    )
    giga_agent_langgraph_dev_http_app: str = Field(
        "", alias="GIGA_AGENT_LANGGRAPH_DEV_HTTP_APP"
    )
    giga_agent_langgraph_dev_http_config_json: str | None = Field(
        None, alias="GIGA_AGENT_LANGGRAPH_DEV_HTTP_CONFIG_JSON"
    )

    giga_agent_local_sandbox_enabled: bool = Field(
        True, alias="GIGA_AGENT_LOCAL_SANDBOX_ENABLED"
    )
    giga_agent_local_docker_image: str = Field(
        "mikelarg/code-interpreter:0.0.7",
        alias="GIGA_AGENT_LOCAL_DOCKER_IMAGE",
    )
    giga_agent_local_docker_memory_limit_mb: int = Field(
        2048, alias="GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB"
    )
    giga_agent_local_docker_memory_reservation_mb: int = Field(
        512,
        alias="GIGA_AGENT_LOCAL_DOCKER_MEMORY_RESERVATION_MB",
    )
    giga_agent_local_docker_vcpu: float = Field(
        1.0, alias="GIGA_AGENT_LOCAL_DOCKER_VCPU"
    )
    giga_agent_local_docker_pids_limit: int = Field(
        256, alias="GIGA_AGENT_LOCAL_DOCKER_PIDS_LIMIT"
    )
    giga_agent_local_docker_shm_size_mb: int = Field(
        128, alias="GIGA_AGENT_LOCAL_DOCKER_SHM_SIZE_MB"
    )
    giga_agent_local_docker_nofile_soft: int = Field(
        1024, alias="GIGA_AGENT_LOCAL_DOCKER_NOFILE_SOFT"
    )
    giga_agent_local_docker_nofile_hard: int = Field(
        4096, alias="GIGA_AGENT_LOCAL_DOCKER_NOFILE_HARD"
    )
    giga_agent_local_docker_startup_timeout_sec: int = Field(
        20, alias="GIGA_AGENT_LOCAL_DOCKER_STARTUP_TIMEOUT_SEC"
    )
    giga_agent_local_docker_max_active_sandboxes: int | None = Field(
        3, alias="GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES"
    )
    giga_agent_local_docker_readonly_rootfs: bool = Field(
        False, alias="GIGA_AGENT_LOCAL_DOCKER_READONLY_ROOTFS"
    )
    giga_agent_local_docker_files_path: Path | None = Field(
        None, alias="GIGA_AGENT_LOCAL_DOCKER_FILES_PATH"
    )
    # --- in-guest SandboxAPI Server (local_docker + e2b работают ТОЛЬКО через него) ---
    giga_agent_sandbox_api_port: int = Field(
        49999, alias="GIGA_AGENT_SANDBOX_API_PORT"
    )
    giga_agent_sandbox_api_startup_timeout_sec: int = Field(
        30, alias="GIGA_AGENT_SANDBOX_API_STARTUP_TIMEOUT_SEC"
    )
    giga_agent_local_jupyter_startup_timeout_sec: int = Field(
        20, alias="GIGA_AGENT_LOCAL_JUPYTER_STARTUP_TIMEOUT_SEC"
    )
    # Time budget for a single kernel to come up: covers both the ``POST
    # /api/kernels`` request and the WebSocket ``/channels`` opening handshake
    # (the server only completes that handshake once the kernel is connected).
    # The default matters under load/cold-start — the first ipykernel launch in
    # a heavy venv can exceed the ``websockets`` library default of 10s and would
    # otherwise fail with an opaque "timed out during opening handshake".
    giga_agent_local_jupyter_kernel_startup_timeout_sec: int = Field(
        60, alias="GIGA_AGENT_LOCAL_JUPYTER_KERNEL_STARTUP_TIMEOUT_SEC"
    )
    giga_agent_local_jupyter_graceful_shutdown_timeout_sec: int = Field(
        5, alias="GIGA_AGENT_LOCAL_JUPYTER_GRACEFUL_SHUTDOWN_TIMEOUT_SEC"
    )
    # Liveness-probe budget for an already-running server (pid alive). Kept well
    # above the startup poll's 1.5s so a momentarily-busy server under CPU/RAM
    # pressure isn't mistaken for dead — which would spawn a duplicate server and
    # double the load (a death spiral on constrained containers).
    giga_agent_local_jupyter_health_probe_timeout_sec: int = Field(
        10, alias="GIGA_AGENT_LOCAL_JUPYTER_HEALTH_PROBE_TIMEOUT_SEC"
    )
    giga_agent_local_jupyter_working_dir: Path | None = Field(
        None, alias="GIGA_AGENT_LOCAL_JUPYTER_WORKING_DIR"
    )
    giga_agent_local_jupyter_files_path: Path | None = Field(
        None, alias="GIGA_AGENT_LOCAL_JUPYTER_FILES_PATH"
    )
    giga_agent_local_jupyter_runtime_dir: Path | None = Field(
        None, alias="GIGA_AGENT_LOCAL_JUPYTER_RUNTIME_DIR"
    )
    giga_agent_local_jupyter_python_executable: str | None = Field(
        None, alias="GIGA_AGENT_LOCAL_JUPYTER_PYTHON_EXECUTABLE"
    )
    giga_agent_local_jupyter_secure_exec_default: bool = Field(
        False, alias="GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_DEFAULT"
    )
    giga_agent_local_jupyter_secure_exec_backend: str = Field(
        "auto", alias="GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_BACKEND"
    )
    giga_agent_local_jupyter_allowed_read_roots: list[Path] = Field(
        default_factory=lambda: [Path("/")],
        alias="GIGA_AGENT_LOCAL_JUPYTER_ALLOWED_READ_ROOTS",
    )
    giga_agent_local_jupyter_allowed_write_roots: list[Path] = Field(
        default_factory=list,
        alias="GIGA_AGENT_LOCAL_JUPYTER_ALLOWED_WRITE_ROOTS",
    )
    giga_agent_local_jupyter_deny_read_roots: list[Path] = Field(
        default_factory=list,
        alias="GIGA_AGENT_LOCAL_JUPYTER_DENY_READ_ROOTS",
    )
    giga_agent_local_jupyter_network_mode: str = Field(
        "host", alias="GIGA_AGENT_LOCAL_JUPYTER_NETWORK_MODE"
    )
    giga_agent_local_jupyter_max_kernels_per_user: int = Field(
        5,
        alias="GIGA_AGENT_LOCAL_JUPYTER_MAX_KERNELS_PER_USER",
        description=(
            "Maximum number of simultaneous local Jupyter kernels per user. "
            "When the limit is reached the least-recently-used kernel of the "
            "owner is evicted before a new one is created. 0 disables the limit."
        ),
    )

    giga_agent_qdrant_pool_size: int | None = Field(
        None, alias="GIGA_AGENT_QDRANT_POOL_SIZE"
    )

    giga_agent_scraper_jina_base_url: str = Field(
        "https://r.jina.ai/",
        alias="GIGA_AGENT_SCRAPER_JINA_BASE_URL",
    )
    giga_agent_scraper_total_concurrency: int = Field(
        3, alias="GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY"
    )
    giga_agent_scraper_disabled: bool = Field(
        False, alias="GIGA_AGENT_SCRAPER_DISABLED"
    )

    giga_agent_enable_think_tool: bool = Field(
        True, alias="GIGA_AGENT_ENABLE_THINK_TOOL"
    )
    giga_agent_enable_think_tool_providers: list[str] = Field(
        default_factory=lambda: ["gigachat"],
        alias="GIGA_AGENT_ENABLE_THINK_TOOL_PROVIDERS",
    )
    giga_agent_enable_multi_tool_use: bool = Field(
        True, alias="GIGA_AGENT_ENABLE_MULTI_TOOL_USE"
    )
    giga_agent_enable_multi_tool_use_providers: list[str] = Field(
        default_factory=lambda: ["gigachat"],
        alias="GIGA_AGENT_ENABLE_MULTI_TOOL_USE_PROVIDERS",
    )

    giga_agent_tool_max_size: int = Field(25000, alias="GIGA_AGENT_TOOL_MAX_SIZE")

    # CSP applied to MCP App (UI widget) iframes to restrict their network
    # egress. Empty/unset → NO restriction (widget may reach any host). Set to a
    # full policy string to lock it down, e.g.:
    #   default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://esm.sh;
    #   style-src 'unsafe-inline' https://esm.sh; img-src data: blob: https://esm.sh;
    #   font-src data: https://esm.sh; connect-src https://esm.sh
    # Disabled for now (None).
    giga_agent_mcp_ui_csp: str | None = Field(None, alias="GIGA_AGENT_MCP_UI_CSP")

    # MCP session pool. "embedded" keeps a small set of warm MCP sessions in the
    # main process (skips the ~0.5s connect+initialize handshake on reuse and
    # warms cold server paths); "off" reverts to open-a-session-per-call. A
    # future "remote" mode will point at a standalone pool service (own pod).
    giga_agent_mcp_pool_mode: str = Field("embedded", alias="GIGA_AGENT_MCP_POOL_MODE")
    # Max warm sessions per (user, server). Replaces the old per-server cap.
    giga_agent_mcp_pool_max_per_server: int = Field(
        4, alias="GIGA_AGENT_MCP_POOL_MAX_PER_SERVER"
    )
    # Per-(user, server) cap for OAuth servers specifically. Kept at 1 so token
    # refresh is serialized in-pod for free (no cross-session rotation race);
    # raising it reintroduces concurrent-refresh hazards (see pool.py notes).
    giga_agent_mcp_pool_max_per_server_oauth: int = Field(
        1, alias="GIGA_AGENT_MCP_POOL_MAX_PER_SERVER_OAUTH"
    )
    # Max warm sessions a single user may hold across all servers.
    giga_agent_mcp_pool_max_per_user: int = Field(
        8, alias="GIGA_AGENT_MCP_POOL_MAX_PER_USER"
    )
    # Hard ceiling on warm sessions across the whole process.
    giga_agent_mcp_pool_max_total: int = Field(
        200, alias="GIGA_AGENT_MCP_POOL_MAX_TOTAL"
    )
    # Evict a warm session after this many idle seconds.
    giga_agent_mcp_pool_idle_ttl_sec: int = Field(
        300, alias="GIGA_AGENT_MCP_POOL_IDLE_TTL_SEC"
    )
    # Recycle a session after this many seconds of life (bounds token/state
    # staleness even if it stays busy).
    giga_agent_mcp_pool_max_lifetime_sec: int = Field(
        1800, alias="GIGA_AGENT_MCP_POOL_MAX_LIFETIME_SEC"
    )

    giga_agent_sandbox_idle_sweeper_enabled: bool = Field(
        True, alias="GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED"
    )
    giga_agent_sandbox_idle_sweeper_interval_sec: int = Field(
        60, alias="GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC"
    )
    giga_agent_sandbox_idle_sweeper_lock_key: str = Field(
        "sandbox:idle-cleanup:lock",
        alias="GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY",
    )
    giga_agent_sandbox_idle_sweeper_lock_ttl_sec: int = Field(
        55, alias="GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC"
    )
    giga_agent_sandbox_starting_ttl_sec: int = Field(
        120, alias="GIGA_AGENT_SANDBOX_STARTING_TTL_SEC"
    )
    giga_agent_sandbox_orphan_sweeper_enabled: bool = Field(
        True, alias="GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_ENABLED"
    )
    giga_agent_sandbox_orphan_sweeper_interval_sec: int = Field(
        120, alias="GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_INTERVAL_SEC"
    )
    giga_agent_sandbox_orphan_sweeper_lock_key: str = Field(
        "sandbox:orphan-cleanup:lock",
        alias="GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_KEY",
    )
    giga_agent_sandbox_orphan_sweeper_lock_ttl_sec: int = Field(
        110, alias="GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_TTL_SEC"
    )
    giga_agent_sandbox_orphan_sweeper_concurrency: int = Field(
        1, alias="GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_CONCURRENCY"
    )

    giga_agent_scheduler_enabled: bool = Field(
        True, alias="GIGA_AGENT_SCHEDULER_ENABLED"
    )
    giga_agent_scheduler_interval_sec: int = Field(
        20, alias="GIGA_AGENT_SCHEDULER_INTERVAL_SEC"
    )
    giga_agent_scheduler_lock_key: str = Field(
        "scheduled-tasks:tick:lock",
        alias="GIGA_AGENT_SCHEDULER_LOCK_KEY",
    )
    giga_agent_scheduler_lock_ttl_sec: int = Field(
        55, alias="GIGA_AGENT_SCHEDULER_LOCK_TTL_SEC"
    )
    giga_agent_scheduler_run_timeout_sec: int = Field(
        600, alias="GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC"
    )
    giga_agent_scheduler_max_concurrent_runs: int = Field(
        2, alias="GIGA_AGENT_SCHEDULER_MAX_CONCURRENT_RUNS"
    )
    # Default timezone for scheduling (cron). Empty -> system local timezone.
    giga_agent_timezone: str = Field("", alias="GIGA_AGENT_TIMEZONE")

    @field_validator("giga_agent_prefix_api", mode="after")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        return (value or "/agent").rstrip("/")

    @field_validator("giga_agent_base_url", mode="after")
    @classmethod
    def _normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        parsed = urlsplit(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("GIGA_AGENT_BASE_URL must be a valid http(s) URL")
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", ""),
        )

    @field_validator("giga_agent_frontend_dir", mode="after")
    @classmethod
    def _normalize_frontend_dir(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("giga_agent_docker_network", mode="after")
    @classmethod
    def _normalize_docker_network(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator(
        "giga_agent_public_base_domain",
        "giga_agent_sandbox_port_redirect_base",
        "giga_agent_app_cookie_domain",
        mode="after",
    )
    @classmethod
    def _normalize_public_base_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower().rstrip(".")
        return cleaned or None

    @field_validator(
        "giga_agent_project_root",
        "giga_agent_host_project_path",
        "giga_agent_local_docker_files_path",
        "giga_agent_local_jupyter_working_dir",
        "giga_agent_local_jupyter_files_path",
        "giga_agent_local_jupyter_runtime_dir",
        mode="after",
    )
    @classmethod
    def _expand_paths(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return value.expanduser()

    @field_validator(
        "giga_agent_local_jupyter_allowed_read_roots",
        "giga_agent_local_jupyter_allowed_write_roots",
        "giga_agent_local_jupyter_deny_read_roots",
        mode="before",
    )
    @classmethod
    def _parse_path_list(cls, value: Any) -> list[Path]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return []
            if cleaned.startswith("["):
                parsed = json.loads(cleaned)
                return [Path(item).expanduser() for item in parsed]
            separator = "," if "," in cleaned else os.pathsep
            return [
                Path(item.strip()).expanduser()
                for item in cleaned.split(separator)
                if item.strip()
            ]
        return [Path(item).expanduser() for item in value]

    @field_validator("giga_agent_local_jupyter_network_mode", mode="after")
    @classmethod
    def _normalize_local_jupyter_network_mode(cls, value: str) -> str:
        cleaned = (value or "host").strip().lower()
        if cleaned not in {"host", "none"}:
            raise ValueError("GIGA_AGENT_LOCAL_JUPYTER_NETWORK_MODE must be host or none")
        return cleaned

    @field_validator("giga_agent_local_jupyter_secure_exec_backend", mode="after")
    @classmethod
    def _normalize_local_jupyter_secure_exec_backend(cls, value: str) -> str:
        cleaned = (value or "auto").strip().lower()
        if cleaned not in {"auto", "macos_sandbox_exec", "linux_bwrap"}:
            raise ValueError(
                "GIGA_AGENT_LOCAL_JUPYTER_SECURE_EXEC_BACKEND must be "
                "auto, macos_sandbox_exec, or linux_bwrap"
            )
        return cleaned

    @field_validator("giga_agent_scraper_jina_base_url", mode="after")
    @classmethod
    def _normalize_jina_base_url(cls, value: str) -> str:
        cleaned = (value or "https://r.jina.ai/").strip()
        if not cleaned.endswith("/"):
            cleaned += "/"
        return cleaned

    @field_validator("giga_agent_log_level", mode="after")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return (value or "INFO").upper()

    @field_validator(
        "giga_agent_sandbox_idle_sweeper_interval_sec",
        mode="after",
    )
    @classmethod
    def _min_idle_interval(cls, value: int) -> int:
        return max(value, 10)

    @field_validator("giga_agent_sandbox_idle_sweeper_lock_ttl_sec", mode="after")
    @classmethod
    def _min_idle_lock_ttl(cls, value: int) -> int:
        return max(value, 5)

    @field_validator("giga_agent_startup_migrations_lock_ttl_sec", mode="after")
    @classmethod
    def _min_startup_migration_lock_ttl(cls, value: int) -> int:
        return max(value, 5)

    @field_validator("giga_agent_sandbox_starting_ttl_sec", mode="after")
    @classmethod
    def _min_starting_ttl(cls, value: int) -> int:
        return max(value, 10)

    @field_validator("giga_agent_sandbox_orphan_sweeper_interval_sec", mode="after")
    @classmethod
    def _min_orphan_interval(cls, value: int) -> int:
        return max(value, 10)

    @field_validator("giga_agent_sandbox_orphan_sweeper_lock_ttl_sec", mode="after")
    @classmethod
    def _min_orphan_lock_ttl(cls, value: int) -> int:
        return max(value, 5)

    @field_validator("giga_agent_sandbox_orphan_sweeper_concurrency", mode="after")
    @classmethod
    def _min_orphan_concurrency(cls, value: int) -> int:
        return max(value, 1)

    @field_validator("giga_agent_scheduler_interval_sec", mode="after")
    @classmethod
    def _min_scheduler_interval(cls, value: int) -> int:
        return max(value, 10)

    @field_validator("giga_agent_scheduler_lock_ttl_sec", mode="after")
    @classmethod
    def _min_scheduler_lock_ttl(cls, value: int) -> int:
        return max(value, 5)

    @field_validator("giga_agent_scheduler_max_concurrent_runs", mode="after")
    @classmethod
    def _min_scheduler_concurrency(cls, value: int) -> int:
        return max(value, 1)

    @field_validator("giga_agent_local_jupyter_startup_timeout_sec", mode="after")
    @classmethod
    def _min_local_jupyter_startup_timeout(cls, value: int) -> int:
        return max(value, 1)

    @field_validator(
        "giga_agent_local_jupyter_kernel_startup_timeout_sec", mode="after"
    )
    @classmethod
    def _min_local_jupyter_kernel_startup_timeout(cls, value: int) -> int:
        return max(value, 1)

    @field_validator(
        "giga_agent_local_jupyter_health_probe_timeout_sec", mode="after"
    )
    @classmethod
    def _min_local_jupyter_health_probe_timeout(cls, value: int) -> int:
        return max(value, 1)

    @field_validator(
        "giga_agent_local_jupyter_graceful_shutdown_timeout_sec",
        mode="after",
    )
    @classmethod
    def _min_local_jupyter_shutdown_timeout(cls, value: int) -> int:
        return max(value, 1)

    @field_validator("giga_agent_scraper_total_concurrency", mode="after")
    @classmethod
    def _min_scraper_total_concurrency(cls, value: int) -> int:
        return max(value, 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def get_local_docker_max_active_sandboxes_from_env() -> int | None:
    raw = (os.getenv("GIGA_AGENT_LOCAL_DOCKER_MAX_ACTIVE_SANDBOXES") or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed


GIGA_AGENT_PREFIX_API = get_settings().giga_agent_prefix_api
GIGA_PREFIX_API = GIGA_AGENT_PREFIX_API
GIGA_AGENT_RUNTIME = get_settings().giga_agent_runtime
GIGA_AGENT_RUNTIME_LOCAL = get_settings().giga_agent_runtime_local
GIGA_AGENT_CLI_CWD = get_settings().giga_agent_cli_cwd
GIGA_AGENT_STT_RUNTIME = get_settings().giga_agent_stt_runtime
GIGA_AGENT_BASE_URL = get_settings().giga_agent_base_url
GIGA_AGENT_FRONTEND_DIR = get_settings().giga_agent_frontend_dir
GIGA_AGENT_UI = get_settings().giga_agent_ui
GIGA_AGENT_UI_PREFIX = get_settings().giga_agent_ui_prefix
GIGA_AGENT_GIGACHAT_FROM_ENV = get_settings().giga_agent_gigachat_from_env
GIGA_AGENT_GIGACHAT_SKIP_CACHE_TOKEN = (
    get_settings().giga_agent_gigachat_skip_cache_token
)

GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED = (
    get_settings().giga_agent_sandbox_idle_sweeper_enabled
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC = (
    get_settings().giga_agent_sandbox_idle_sweeper_interval_sec
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY = (
    get_settings().giga_agent_sandbox_idle_sweeper_lock_key
)
GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC = (
    get_settings().giga_agent_sandbox_idle_sweeper_lock_ttl_sec
)
GIGA_AGENT_SANDBOX_STARTING_TTL_SEC = get_settings().giga_agent_sandbox_starting_ttl_sec
GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_ENABLED = (
    get_settings().giga_agent_sandbox_orphan_sweeper_enabled
)
GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_INTERVAL_SEC = (
    get_settings().giga_agent_sandbox_orphan_sweeper_interval_sec
)
GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_KEY = (
    get_settings().giga_agent_sandbox_orphan_sweeper_lock_key
)
GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_TTL_SEC = (
    get_settings().giga_agent_sandbox_orphan_sweeper_lock_ttl_sec
)
GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_CONCURRENCY = (
    get_settings().giga_agent_sandbox_orphan_sweeper_concurrency
)
GIGA_AGENT_SCHEDULER_ENABLED = get_settings().giga_agent_scheduler_enabled
GIGA_AGENT_SCHEDULER_INTERVAL_SEC = get_settings().giga_agent_scheduler_interval_sec
GIGA_AGENT_SCHEDULER_LOCK_KEY = get_settings().giga_agent_scheduler_lock_key
GIGA_AGENT_SCHEDULER_LOCK_TTL_SEC = get_settings().giga_agent_scheduler_lock_ttl_sec
GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC = (
    get_settings().giga_agent_scheduler_run_timeout_sec
)
GIGA_AGENT_SCHEDULER_MAX_CONCURRENT_RUNS = (
    get_settings().giga_agent_scheduler_max_concurrent_runs
)
GIGA_AGENT_TIMEZONE = get_settings().giga_agent_timezone
GIGA_AGENT_ENABLE_THINK_TOOL = get_settings().giga_agent_enable_think_tool
GIGA_AGENT_ENABLE_THINK_TOOL_PROVIDERS = (
    get_settings().giga_agent_enable_think_tool_providers
)
GIGA_AGENT_ENABLE_MULTI_TOOL_USE = get_settings().giga_agent_enable_multi_tool_use
GIGA_AGENT_ENABLE_MULTI_TOOL_USE_PROVIDERS = (
    get_settings().giga_agent_enable_multi_tool_use_providers
)
GIGA_AGENT_SKIP_STARTUP_MIGRATIONS = get_settings().giga_agent_skip_startup_migrations
GIGA_AGENT_SKIP_ONBOARDING = get_settings().giga_agent_skip_onboarding
GIGA_AGENT_EXPERIMENTAL_MODE = get_settings().giga_agent_experimental_mode
GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL = (
    get_settings().giga_agent_experimental_rewrite_model
)
GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL = (
    get_settings().giga_agent_experimental_status_model
)
GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_KEY = (
    get_settings().giga_agent_startup_migrations_lock_key
)
GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_TTL_SEC = (
    get_settings().giga_agent_startup_migrations_lock_ttl_sec
)
