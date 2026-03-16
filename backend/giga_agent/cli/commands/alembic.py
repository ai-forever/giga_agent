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
    get_core_migration_scope,
    get_module_migration_scope,
    wait_for_db,
)
from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def alembic(
    ctx: typer.Context,
    agent_path: Annotated[
        str,
        typer.Argument(help="Path to agent instance, e.g. giga_agent.agents.run:agent"),
    ] = "giga_agent.agents.run:agent",
    scope: Annotated[
        str,
        typer.Option("--scope", help="Migration scope: core or a module id."),
    ] = "core",
) -> None:
    """
    Proxies Alembic commands after loading agent modules (so models exist).

    Example:
        uv run giga_agent alembic --agent-path giga_agent.agents.run:agent upgrade head
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

    if scope == "core":
        try:
            import giga_agent.models  # noqa: F401
        except Exception:
            pass
        selected_scope = get_core_migration_scope()
    else:
        selected_scope = None
        for mod in agent.all_modules:
            if getattr(mod, "id", None) != scope:
                continue
            try:
                mod.get_models()
            except Exception as e:
                logger.warning(
                    f"Could not load models via get_models() for module "
                    f"'{getattr(mod, 'id', '?')}': {e}"
                )
            selected_scope = get_module_migration_scope(mod)
            break

    if selected_scope is None:
        logger.error("Unknown or unavailable migration scope: %s", scope)
        raise typer.Exit(code=1)

    if not os.path.isdir(selected_scope.migration_path):
        logger.info("No migrations found for scope '%s'.", scope)
        raise typer.Exit(code=0)

    alembic_cfg = _get_alembic_config(
        os.pathsep.join(selected_scope.version_locations),
        selected_scope.version_table,
    )

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
        wants_autogen = bool(getattr(options, "autogenerate", False))
        is_revision = cmd_fn is alembic_command.revision
        if is_revision and wants_autogen:
            if not hasattr(options, "x") or options.x is None:
                options.x = []
            options.x.append(f"target_prefix={selected_scope.target_prefix}")
    except Exception:
        pass

    try:
        wants_sql_only = bool(getattr(options, "sql", False))

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
