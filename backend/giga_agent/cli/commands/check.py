from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging

from ..migrations.common import (
    _get_alembic_config,
    check_db_is_up_to_date,
    get_agent_migration_scopes,
    get_core_migration_scope,
)
from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def check(
    agent_path: Annotated[
        str,
        typer.Argument(
            help="Path to agent instance, e.g. giga_agent.agents.run:agent",
        ),
    ] = "giga_agent.agents.run:agent",
    scope: Annotated[
        str,
        typer.Option("--scope", help="Migration scope: all, core, or a module id."),
    ] = "all",
) -> None:
    """
    Validates migration history for core/modules and checks DB state.
    """
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    reset_settings_cache()
    setup_cli_logging("INFO")

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        raise typer.Exit(code=1)

    available_scopes = get_agent_migration_scopes(agent)
    if scope == "all":
        selected_scopes = available_scopes
    elif scope == "core":
        core_scope = get_core_migration_scope()
        selected_scopes = [core_scope] if core_scope is not None else []
    else:
        selected_scopes = [s for s in available_scopes if s.scope_id == scope]
        if not selected_scopes:
            logger.error("Unknown migration scope: %s", scope)
            raise typer.Exit(code=1)

    if not selected_scopes:
        logger.info("No migrations found.")
        return

    db_url = get_db_url()
    has_errors = False

    for migration_scope in selected_scopes:
        if not os.path.isdir(migration_scope.migration_path):
            logger.info(
                "No migrations directory for scope '%s'; skipping.",
                migration_scope.scope_id,
            )
            continue

        cfg = _get_alembic_config(
            os.pathsep.join(migration_scope.version_locations),
            migration_scope.version_table,
        )
        if db_url:
            cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

        try:
            script = ScriptDirectory.from_config(cfg)
            heads = list(script.get_heads() or ())
            if len(heads) > 1:
                logger.error(
                    "CONFLICT detected in scope '%s': multiple heads %s",
                    migration_scope.scope_id,
                    heads,
                )
                has_errors = True
                continue

            if heads:
                logger.info(
                    "OK: scope '%s' (head=%s, version_table=%s)",
                    migration_scope.scope_id,
                    heads[0],
                    migration_scope.version_table,
                )
            else:
                logger.info("OK: scope '%s' has no revisions yet.", migration_scope.scope_id)

            check_db_is_up_to_date(
                cfg,
                scope_label=migration_scope.scope_id,
                target_prefix=(
                    migration_scope.target_prefix
                    if migration_scope.kind == "module"
                    else None
                ),
            )
        except SystemExit:
            has_errors = True
        except Exception as e:
            logger.warning(
                "Could not check scope '%s': %s",
                migration_scope.scope_id,
                e,
            )
            has_errors = True

    if has_errors:
        logger.error("Migration validation failed! Please resolve conflicts.")
        sys.exit(1)

    logger.info("Migration validation passed for selected scope(s).")
