from __future__ import annotations

import os
from typing import Annotated

import typer
from alembic import command as alembic_command

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging

from ..migrations.common import (
    _get_alembic_config,
    _get_core_models_migration_path,
    wait_for_db,
)
from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def alembic(
    ctx: typer.Context,
    agent_path: Annotated[
        str,
        typer.Option(help="Path to agent instance, e.g. giga_agent.agents.run:agent"),
    ] = "giga_agent.agents.run:agent",
) -> None:
    """
    Proxies Alembic commands after loading agent modules (so models exist).

    Example:
        uv run giga_agent alembic --agent-path giga_agent.agents.run:agent upgrade heads
    """
    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    reset_settings_cache()
    setup_cli_logging("INFO")

    argv = list(ctx.args or [])
    if not argv:
        raise typer.BadParameter(
            "Alembic args are required, e.g. 'upgrade head' or 'revision -m \"msg\"'."
        )

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        typer.secho("Failed to load agent. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Primary model loading path for autogenerate scenarios.
    try:
        import giga_agent.models  # noqa: F401
    except Exception:
        pass

    # Keep module-level hooks as best-effort only.
    for mod in agent.all_modules:
        try:
            mod.get_models()
        except Exception as e:
            logger.warning(
                f"Could not load models via get_models() for module "
                f"'{getattr(mod, 'id', '?')}': {e}"
            )

    migration_paths: list[str] = []

    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    for mod in agent.all_modules:
        if getattr(mod, "migration_path", None):
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        raise typer.Exit(code=0)

    version_locations = os.pathsep.join(migration_paths)
    alembic_cfg = _get_alembic_config(version_locations)

    db_url = get_db_url()
    if db_url:
        alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

    from alembic.config import CommandLine

    alembic_cli = CommandLine()
    try:
        options = alembic_cli.parser.parse_args(argv)
    except SystemExit as e:
        raise typer.Exit(code=int(getattr(e, "code", 0) or 0))

    alembic_cfg.cmd_opts = options

    try:
        cmd_fn = getattr(options, "cmd", (None, None, None))[0]
        wants_sql_only = bool(getattr(options, "sql", False))
        is_revision = cmd_fn is alembic_command.revision
        wants_autogen = bool(getattr(options, "autogenerate", False))

        should_wait_for_db = (
            bool(db_url) and not wants_sql_only and (not is_revision or wants_autogen)
        )
        if should_wait_for_db and db_url:
            wait_for_db(db_url)
    except Exception:
        pass

    try:
        alembic_cli.run_cmd(alembic_cfg, options)
    except Exception as e:
        logger.exception("Alembic command failed")
        typer.secho(f"Alembic command failed: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
