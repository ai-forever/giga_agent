from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent

logger = get_logger(__name__)


class MigrationApplyError(RuntimeError):
    """Raised when automatic migration application fails."""


def _get_core_models_migration_path() -> str:
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _get_alembic_config(version_locations: str) -> Config:
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
    return alembic_cfg


def apply_migrations(agent: BaseAgent, target: str = "heads") -> None:
    """
    Collects migration paths (core + modules) and runs `alembic upgrade <target>`.
    """
    migration_paths: list[str] = []

    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        logger.info(f"Found core models migrations: {core_migrations}")
        migration_paths.append(core_migrations)

    for mod in agent.all_modules:
        if getattr(mod, "migration_path", None):
            logger.info(
                f"Found migrations for {mod.__class__.__name__}: {mod.migration_path}"
            )
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        return

    version_locations = os.pathsep.join(migration_paths)

    db_url = get_db_url()
    alembic_cfg = _get_alembic_config(version_locations)
    alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

    if db_url:
        wait_for_db(db_url)

    logger.info(
        "Applying migrations from locations: %s (target=%s)",
        version_locations,
        target,
    )
    try:
        command.upgrade(alembic_cfg, target)
        logger.info("Migrations applied successfully!")
    except Exception as e:
        logger.exception("Error applying migrations")
        raise MigrationApplyError(f"Error applying migrations: {e}") from e


__all__ = [
    "_get_alembic_config",
    "_get_core_models_migration_path",
    "MigrationApplyError",
    "apply_migrations",
    "wait_for_db",
]
