from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.module import BaseModule

logger = get_logger(__name__)

_MODULE_ID_RE = re.compile(r"^[a-z0-9_]+$")
_CORE_SCOPE_ID = "core"


class MigrationApplyError(RuntimeError):
    """Raised when automatic migration application fails."""


class ModuleMigrationScopeError(MigrationApplyError):
    """Raised when a module migration scope is invalid or unsafe to apply."""


@dataclass(frozen=True)
class MigrationScope:
    scope_id: str
    kind: Literal["core", "module"]
    version_locations: tuple[str, ...]
    version_table: str
    target_prefix: str
    migration_path: str


def _get_core_models_migration_path() -> str:
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(package_dir, "models", "migrations")


def _normalize_module_import_path(module_import: str) -> str:
    normalized = module_import.strip()
    for suffix in (".module", ".models"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _get_module_target_prefix(mod: BaseModule) -> str:
    module_import = _normalize_module_import_path(mod.__class__.__module__)
    module_name = module_import.split(".")[-1]
    return f"{module_name}_"


def _validate_module_id(module_id: str) -> None:
    if not _MODULE_ID_RE.fullmatch(module_id):
        raise ModuleMigrationScopeError(
            f"Module migration scope id must match ^[a-z0-9_]+$: got '{module_id}'."
        )


def get_core_migration_scope() -> MigrationScope | None:
    migration_path = _get_core_models_migration_path()
    if not os.path.exists(migration_path):
        return None
    return MigrationScope(
        scope_id=_CORE_SCOPE_ID,
        kind="core",
        version_locations=(migration_path,),
        version_table="alembic_version",
        target_prefix="core_",
        migration_path=migration_path,
    )


def get_module_migration_scope(mod: BaseModule) -> MigrationScope:
    _validate_module_id(mod.id)
    migration_path = os.path.join(mod.module_path, "migrations")
    return MigrationScope(
        scope_id=mod.id,
        kind="module",
        version_locations=(migration_path,),
        version_table=f"alembic_version_{mod.id}",
        target_prefix=_get_module_target_prefix(mod),
        migration_path=migration_path,
    )


def get_agent_migration_scopes(agent: BaseAgent) -> list[MigrationScope]:
    scopes: list[MigrationScope] = []
    core_scope = get_core_migration_scope()
    if core_scope is not None:
        scopes.append(core_scope)

    module_scopes = sorted(
        (get_module_migration_scope(mod) for mod in agent.all_modules),
        key=lambda scope: scope.scope_id,
    )
    scopes.extend(module_scopes)
    return scopes


def resolve_requested_scopes(
    agent: BaseAgent,
    requested_scope: str | None = None,
) -> list[MigrationScope]:
    scopes = get_agent_migration_scopes(agent)
    by_id = {scope.scope_id: scope for scope in scopes}

    normalized = (requested_scope or "all").strip()
    if normalized == "all":
        return scopes
    if normalized == _CORE_SCOPE_ID:
        core_scope = by_id.get(_CORE_SCOPE_ID)
        return [core_scope] if core_scope is not None else []

    if normalized not in by_id:
        available = sorted(scope.scope_id for scope in scopes if scope.kind == "module")
        raise ModuleMigrationScopeError(
            f"Unknown migration scope '{normalized}'. "
            f"Available module scopes: {available or '[]'}"
        )

    return [by_id[normalized]]


def wait_for_db(db_url: str, retries: int = 15, delay: int = 2) -> None:
    """
    Checks database availability. Critical for Docker/Postgres cold starts.
    """
    if "sqlite" in db_url:
        return

    logger.info(f"Checking database connection at {db_url}...")

    sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")

    try:
        engine = create_engine(sync_url)
    except Exception as e:
        logger.error(f"Could not create sync engine for check: {e}")
        return

    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database is ready!")
            return
        except OperationalError:
            logger.info(f"Database not ready yet. Retrying {i + 1}/{retries}...")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"Error checking DB: {e}")
            return

    logger.error("Could not connect to database after multiple retries.")
    sys.exit(1)


def _get_alembic_config(version_locations: str, version_table: str) -> Config:
    """
    Helper to create Alembic Config with dynamic version locations.

    NOTE: We intentionally load `alembic.ini` from the installed `giga_agent`
    package to avoid accidentally picking up a user's unrelated `alembic.ini`
    from the current working directory.
    """
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini_path = os.path.join(package_dir, "alembic.ini")
    if not os.path.exists(alembic_ini_path):
        raise FileNotFoundError(
            "alembic.ini not found inside the installed giga_agent package at: "
            f"{alembic_ini_path}. "
            "This is required for migrations; ensure package data is included in the build."
        )

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("version_locations", version_locations)
    alembic_cfg.set_main_option("version_table", version_table)
    return alembic_cfg


def _inspect_schema_state(db_url: str, scope: MigrationScope) -> tuple[bool, bool]:
    sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            table_names = set(inspector.get_table_names())
    finally:
        engine.dispose()

    has_version_table = scope.version_table in table_names
    has_prefixed_tables = any(
        table_name.startswith(scope.target_prefix) for table_name in table_names
    )
    return has_version_table, has_prefixed_tables


def _scope_has_migration_files(scope: MigrationScope) -> bool:
    if not os.path.isdir(scope.migration_path):
        return False
    return any(
        file_name.endswith(".py") and not file_name.startswith("__")
        for file_name in os.listdir(scope.migration_path)
    )


def _guard_module_scope_state(scope: MigrationScope, db_url: str) -> None:
    if scope.kind != "module":
        return

    has_version_table, has_prefixed_tables = _inspect_schema_state(db_url, scope)
    if not has_version_table and has_prefixed_tables:
        raise ModuleMigrationScopeError(
            "legacy/manual module schema detected; create version table explicitly "
            f"or clean schema (scope={scope.scope_id}, prefix='{scope.target_prefix}')."
        )


def apply_scope_migrations(
    scope: MigrationScope,
    *,
    target: str = "head",
    db_url: str | None = None,
) -> None:
    """
    Applies migrations for a single scope.
    """
    effective_db_url = db_url or get_db_url()
    if effective_db_url:
        _guard_module_scope_state(scope, effective_db_url)

    if not _scope_has_migration_files(scope):
        # logger.info("No migration files found for scope '%s'. Skipping.", scope.scope_id)
        return

    alembic_cfg = _get_alembic_config(
        os.pathsep.join(scope.version_locations),
        scope.version_table,
    )
    if effective_db_url:
        alembic_cfg.set_section_option("alembic", "sqlalchemy.url", effective_db_url)

    logger.info(
        "Applying migrations for scope '%s' from %s (target=%s, version_table=%s)",
        scope.scope_id,
        os.pathsep.join(scope.version_locations),
        target,
        scope.version_table,
    )
    command.upgrade(alembic_cfg, target)


def apply_app_migrations(
    agent: BaseAgent,
    target: str = "head",
    requested_scope: str | None = None,
) -> None:
    """
    Applies migrations for core and/or module scopes.
    """
    scopes = resolve_requested_scopes(agent, requested_scope=requested_scope)
    if not scopes:
        logger.info("No migrations found.")
        return

    db_url = get_db_url()
    if db_url:
        wait_for_db(db_url)

    try:
        for scope in scopes:
            apply_scope_migrations(scope, target=target, db_url=db_url)
        logger.info("Migrations applied successfully!")
    except Exception as e:
        logger.exception("Error applying migrations")
        raise MigrationApplyError(f"Error applying migrations: {e}") from e


def apply_migrations(
    agent: BaseAgent,
    target: str = "head",
    requested_scope: str | None = None,
) -> None:
    """
    Backwards-compatible wrapper over scope-based migration application.
    """
    apply_app_migrations(agent, target=target, requested_scope=requested_scope)


__all__ = [
    "_get_alembic_config",
    "_get_core_models_migration_path",
    "MigrationApplyError",
    "MigrationScope",
    "ModuleMigrationScopeError",
    "apply_app_migrations",
    "apply_migrations",
    "apply_scope_migrations",
    "get_agent_migration_scopes",
    "get_core_migration_scope",
    "get_module_migration_scope",
    "resolve_requested_scopes",
    "wait_for_db",
]
