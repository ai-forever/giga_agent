from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    giga_agent_prefix_api: str = Field("/agent", alias="GIGA_AGENT_PREFIX_API")
    giga_agent_frontend_dir: str | None = Field(None, alias="GIGA_AGENT_FRONTEND_DIR")
    giga_agent_ui: bool = Field(True, alias="GIGA_AGENT_UI")
    giga_agent_ui_prefix: Optional[str] = Field(None, alias="GIGA_AGENT_UI_PREFIX")

    giga_agent_runtime: str = Field("local", alias="GIGA_AGENT_RUNTIME")
    giga_agent_database_url: str | None = Field(None, alias="GIGA_AGENT_DATABASE_URL")
    giga_agent_project_root: Path = Field(
        default_factory=lambda: Path.cwd() / ".giga_agent",
        alias="GIGA_AGENT_PROJECT_ROOT",
    )
    giga_agent_host: str | None = Field(None, alias="GIGA_AGENT_HOST")
    giga_agent_port: str | None = Field(None, alias="GIGA_AGENT_PORT")

    giga_agent_alembic_fileconfig: bool = Field(
        False, alias="GIGA_AGENT_ALEMBIC_FILECONFIG"
    )
    giga_agent_skip_startup_migrations: bool = Field(
        False, alias="GIGA_AGENT_SKIP_STARTUP_MIGRATIONS"
    )
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

    giga_agent_langgraph_api_url: str | None = Field(
        None, alias="GIGA_AGENT_LANGGRAPH_API_URL"
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
    giga_agent_local_docker_memory_limit_mb: int = Field(
        512, alias="GIGA_AGENT_LOCAL_DOCKER_MEMORY_LIMIT_MB"
    )
    giga_agent_local_docker_memory_reservation_mb: int = Field(
        512,
        alias="GIGA_AGENT_LOCAL_DOCKER_MEMORY_RESERVATION_MB",
    )
    giga_agent_local_docker_vcpu: float = Field(
        0.3, alias="GIGA_AGENT_LOCAL_DOCKER_VCPU"
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
    giga_agent_local_docker_allow_network: bool = Field(
        True, alias="GIGA_AGENT_LOCAL_DOCKER_ALLOW_NETWORK"
    )
    giga_agent_local_docker_files_path: Path | None = Field(
        None, alias="GIGA_AGENT_LOCAL_DOCKER_FILES_PATH"
    )

    giga_agent_qdrant_pool_size: int | None = Field(
        None, alias="GIGA_AGENT_QDRANT_POOL_SIZE"
    )
    giga_agent_mem0_qdrant_ensure_cache: bool = Field(
        True, alias="GIGA_AGENT_MEM0_QDRANT_ENSURE_CACHE"
    )

    giga_agent_scraper_jina_base_url: str = Field(
        "https://r.jina.ai/",
        alias="GIGA_AGENT_SCRAPER_JINA_BASE_URL",
    )
    giga_agent_scraper_total_concurrency: int = Field(
        8, alias="GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY"
    )

    giga_agent_tool_max_size: int = Field(25000, alias="GIGA_AGENT_TOOL_MAX_SIZE")

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

    @field_validator("giga_agent_prefix_api", mode="after")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        return (value or "/agent").rstrip("/")

    @field_validator("giga_agent_frontend_dir", mode="after")
    @classmethod
    def _normalize_frontend_dir(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator(
        "giga_agent_project_root", "giga_agent_local_docker_files_path", mode="after"
    )
    @classmethod
    def _expand_paths(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return value.expanduser()

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
GIGA_AGENT_FRONTEND_DIR = get_settings().giga_agent_frontend_dir
GIGA_AGENT_UI = get_settings().giga_agent_ui
GIGA_AGENT_UI_PREFIX = get_settings().giga_agent_ui_prefix

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
GIGA_AGENT_SKIP_STARTUP_MIGRATIONS = get_settings().giga_agent_skip_startup_migrations
GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_KEY = (
    get_settings().giga_agent_startup_migrations_lock_key
)
GIGA_AGENT_STARTUP_MIGRATIONS_LOCK_TTL_SEC = (
    get_settings().giga_agent_startup_migrations_lock_ttl_sec
)
