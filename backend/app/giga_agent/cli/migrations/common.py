from __future__ import annotations

import os
import sys
import time
from types import ModuleType

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def _get_core_models_migration_path() -> str:
    package_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(package_dir, "models", "migrations")


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
            logger.info(f"Database not ready yet. Retrying {i+1}/{retries}...")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"Error checking DB: {e}")
            return

    logger.error("Could not connect to database after multiple retries.")
    sys.exit(1)


def _normalize_module_import_path(module_import: str) -> str:
    normalized = module_import.strip()
    for suffix in (".module", ".models"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _get_module_name_and_prefix(module_import: str) -> tuple[str, str]:
    module_name = module_import.split(".")[-1]
    return module_name, f"{module_name}_"


def _get_agent_module_import(mod) -> str:
    return _normalize_module_import_path(mod.__class__.__module__)


def _get_alembic_config(version_locations: str) -> Config:
    """
    Helper to create Alembic Config with dynamic version locations.
    """
    alembic_ini_path = os.path.join(os.getcwd(), "alembic.ini")
    if not os.path.exists(alembic_ini_path):
        package_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        internal_ini_path = os.path.join(package_dir, "alembic.ini")
        if os.path.exists(internal_ini_path):
            logger.info(f"Using internal alembic.ini from {internal_ini_path}")
            alembic_ini_path = internal_ini_path
        else:
            logger.warning(
                "Warning: alembic.ini not found in current directory. Using default defaults might fail."
            )

    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("version_locations", version_locations)
    return alembic_cfg


def apply_migrations(agent: BaseAgent) -> None:
    """
    Collects migration paths (core + modules) and runs `alembic upgrade heads`.
    """
    migration_paths: list[str] = []

    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        logger.info(f"Found core models migrations: {core_migrations}")
        migration_paths.append(core_migrations)

    for mod in agent.modules:
        if getattr(mod, "migration_path", None):
            logger.info(
                f"Found migrations for {mod.__class__.__name__}: {mod.migration_path}"
            )
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        return

    version_locations = " ".join(migration_paths)

    db_url = get_db_url()
    alembic_cfg = _get_alembic_config(version_locations)
    alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

    if db_url:
        wait_for_db(db_url)

    logger.info(f"Applying migrations from locations: {version_locations}")
    try:
        command.upgrade(alembic_cfg, "heads")
        logger.info("Migrations applied successfully!")
    except Exception as e:
        logger.exception("Error applying migrations")
        typer.secho(f"Error applying migrations: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


def check_db_is_up_to_date(alembic_cfg: Config) -> None:
    """
    Checks if the database schema is up-to-date with the codebase migrations.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    db_url = alembic_cfg.get_main_option("sqlalchemy.url") or get_db_url()

    try:
        sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
        engine = create_engine(sync_url)
        conn = engine.connect()
    except Exception as e:
        logger.warning(f"Could not connect to DB for revision check: {e}")
        return

    context = MigrationContext.configure(conn)
    current_heads = list(context.get_current_heads() or ())

    script = ScriptDirectory.from_config(alembic_cfg)
    script_heads = list(script.get_heads() or ())

    if set(current_heads) != set(script_heads):
        logger.error("Database is not up-to-date!")
        logger.error(f"Current DB heads: {current_heads}")
        logger.error(f"Codebase heads: {script_heads}")
        logger.error(
            "Please apply migrations before creating a new one (e.g. run 'uv run giga_agent dev ...')."
        )
        sys.exit(1)

    logger.info("Database is up-to-date.")


# Re-export a few helpers for other CLI modules.
__all__ = [
    "_get_alembic_config",
    "_get_agent_module_import",
    "_get_core_models_migration_path",
    "_get_module_name_and_prefix",
    "_normalize_module_import_path",
    "apply_migrations",
    "check_db_is_up_to_date",
    "wait_for_db",
]

