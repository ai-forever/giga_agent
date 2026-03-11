from __future__ import annotations

import os
from typing import Annotated

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.logging import get_logger, setup_cli_logging
from giga_agent.core.migrations import apply_migrations

from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def migrate(
    agent_path: Annotated[
        str,
        typer.Argument(help="Path to agent instance, e.g. giga_agent.agents.run:agent"),
    ] = "giga_agent.agents.run:agent",
    target: Annotated[
        str,
        typer.Argument(
            help=(
                "Alembic upgrade target revision (upgrade-only), "
                "e.g. head, base, or a specific revision id."
            )
        ),
    ] = "head",
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Migration scope: all, core, or a module id.",
        ),
    ] = "all",
) -> None:
    """
    Applies DB migrations by running `alembic upgrade <target>`.
    """
    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    reset_settings_cache()
    setup_cli_logging("INFO")

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        typer.secho("Failed to load agent. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        apply_migrations(agent, target=target, requested_scope=scope)
    except Exception as e:
        logger.exception("Migrate command failed")
        typer.secho(f"Migrate command failed: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from e
