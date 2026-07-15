from __future__ import annotations

import sys

import typer
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger
from giga_agent.core.migrations import (
    _get_alembic_config,
    _get_core_models_migration_path,
    apply_migrations as _core_apply_migrations,
    get_agent_migration_scopes,
    get_core_migration_scope,
    get_module_migration_scope,
    wait_for_db,
)

logger = get_logger(__name__)


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


def apply_migrations(
    agent,
    target: str = "head",
    requested_scope: str | None = None,
) -> None:
    """
    CLI wrapper over core migration runner.
    Keeps typer.Exit behavior for command UX compatibility.
    """
    try:
        _core_apply_migrations(agent, target=target, requested_scope=requested_scope)
    except Exception as e:
        logger.exception("Error applying migrations")
        typer.secho(f"Error applying migrations: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from e


def check_db_is_up_to_date(
    alembic_cfg: Config,
    *,
    scope_label: str,
    target_prefix: str | None = None,
) -> None:
    """
    Checks if the database schema is up-to-date with the codebase migrations.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    db_url = alembic_cfg.get_main_option("sqlalchemy.url") or get_db_url()
    version_table = alembic_cfg.get_main_option("version_table") or "alembic_version"

    try:
        sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
        engine = create_engine(sync_url)
        conn = engine.connect()
    except Exception as e:
        logger.warning(f"Could not connect to DB for revision check: {e}")
        return

    try:
        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        version_table_exists = version_table in table_names
        prefixed_tables_exist = bool(
            target_prefix
            and any(table_name.startswith(target_prefix) for table_name in table_names)
        )

        if not version_table_exists and prefixed_tables_exist:
            logger.error(
                "legacy/manual module schema detected; create version table explicitly "
                "or clean schema (scope=%s, prefix='%s').",
                scope_label,
                target_prefix,
            )
            sys.exit(1)

        if version_table_exists:
            context = MigrationContext.configure(
                conn,
                opts={
                    "version_table": version_table,
                    "version_table_pk": False,
                },
            )
            current_heads = list(context.get_current_heads() or ())
        else:
            current_heads = []

        script = ScriptDirectory.from_config(alembic_cfg)
        script_heads = list(script.get_heads() or ())
    finally:
        try:
            conn.close()
        finally:
            engine.dispose()

    unknown: list[str] = []
    for head in current_heads:
        try:
            revision = script.get_revision(head)
        except Exception:
            revision = None
        if revision is None:
            unknown.append(head)
    unknown.sort()
    if unknown:
        logger.error(
            "Database contains unknown Alembic revisions for scope '%s'!", scope_label
        )
        logger.error(f"Unknown revisions in DB: {unknown}")
        logger.error(f"Known script heads: {sorted(script_heads)}")
        sys.exit(1)

    missing_heads = set(script_heads) - set(current_heads)
    if missing_heads:
        logger.error("Database is not up-to-date for scope '%s'!", scope_label)
        logger.error(f"Current DB heads: {current_heads}")
        logger.error(f"Codebase heads: {script_heads}")
        logger.error(f"Missing code heads in DB state: {sorted(missing_heads)}")
        logger.error(
            "Please apply migrations before creating a new one (e.g. run 'uv run giga_agent migrate')."
        )
        sys.exit(1)

    logger.info("Database is up-to-date for scope '%s'.", scope_label)


__all__ = [
    "_get_agent_module_import",
    "_get_alembic_config",
    "_get_core_models_migration_path",
    "_get_module_name_and_prefix",
    "_normalize_module_import_path",
    "apply_migrations",
    "check_db_is_up_to_date",
    "get_agent_migration_scopes",
    "get_core_migration_scope",
    "get_module_migration_scope",
    "wait_for_db",
]
