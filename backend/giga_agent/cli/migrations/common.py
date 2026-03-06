from __future__ import annotations

import sys

import typer
from alembic.config import Config
from sqlalchemy import create_engine

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger
from giga_agent.core.migrations import (
    _get_alembic_config,
    _get_core_models_migration_path,
    apply_migrations as _core_apply_migrations,
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


def apply_migrations(agent, target: str = "heads") -> None:
    """
    CLI wrapper over core migration runner.
    Keeps typer.Exit behavior for command UX compatibility.
    """
    try:
        _core_apply_migrations(agent, target=target)
    except Exception as e:
        logger.exception("Error applying migrations")
        typer.secho(f"Error applying migrations: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from e


def check_db_is_up_to_date(
    alembic_cfg: Config, *, allow_unknown_db_heads: bool = False
) -> None:
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

    try:
        # Keep MigrationContext in sync with env.py (multi-head setup).
        # version_table_pk affects table *creation*, but passing it here also ensures
        # consistent behavior if Alembic internals rely on the flag.
        context = MigrationContext.configure(conn, opts={"version_table_pk": False})
        current_heads = list(context.get_current_heads() or ())

        script = ScriptDirectory.from_config(alembic_cfg)
        script_heads = list(script.get_heads() or ())
    finally:
        try:
            conn.close()
        finally:
            engine.dispose()

    # In modular setups, module heads often declare `depends_on=<core_head>`.
    # Alembic may treat such dependency heads as "effective" without storing them
    # as separate rows in the version table. Therefore, comparing raw heads from
    # the DB version table to ScriptDirectory heads is too strict.
    #
    # Instead, consider the DB up-to-date if all script heads are contained in the
    # set of revisions implied by the current DB heads (including dependencies).
    effective_db_revs: set[str] = set()
    if current_heads:
        known_current_heads: list[str] = []
        unknown: list[str] = []

        for head in current_heads:
            try:
                r = script.get_revision(head)
            except Exception:
                r = None
            if r is None:
                unknown.append(head)
            else:
                known_current_heads.append(head)

        if unknown:
            if allow_unknown_db_heads:
                logger.info(
                    "Ignoring DB heads not present in current script "
                    f"(likely other module branches): {sorted(unknown)}"
                )
            else:
                logger.error("Database contains unknown Alembic revisions!")
                logger.error(f"Unknown revisions in DB: {sorted(unknown)}")
                logger.error(f"Known script heads: {sorted(script_heads)}")
                sys.exit(1)

        # Walk down-revisions (including dependencies) from each known current head.
        for head in known_current_heads:
            for r in script.revision_map.iterate_revisions(head, None, inclusive=True):
                effective_db_revs.add(r.revision)

    missing_heads = set(script_heads) - effective_db_revs
    if missing_heads:
        logger.error("Database is not up-to-date!")
        logger.error(f"Current DB heads: {current_heads}")
        logger.error(f"Codebase heads: {script_heads}")
        logger.error(
            f"Missing code heads in effective DB state: {sorted(missing_heads)}"
        )
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
