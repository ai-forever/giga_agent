from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

from giga_agent.core.logging import get_logger, setup_cli_logging

from ..migrations.common import _get_alembic_config, _get_core_models_migration_path
from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def check(
    agent_path: Annotated[
        str, typer.Option(help="Path to agent instance, e.g. agent.py:agent")
    ] = "agent.py:agent",
) -> None:
    """
    Validates migration history for all modules.
    Fails if multiple heads are found in any module (branching history).
    """
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    setup_cli_logging("INFO")

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        raise typer.Exit(code=1)

    migration_paths: list[str] = []

    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    for mod in agent.modules:
        if getattr(mod, "migration_path", None):
            migration_paths.append(mod.migration_path)

    if not migration_paths:
        logger.info("No migrations found.")
        return

    version_locations = os.pathsep.join(migration_paths)
    alembic_cfg = _get_alembic_config(version_locations)

    script = ScriptDirectory.from_config(alembic_cfg)
    _ = script.get_heads()

    has_errors = False

    for path in migration_paths:
        try:
            if os.path.abspath(path) == os.path.abspath(core_migrations):
                single_cfg = _get_alembic_config(path)
                single_script = ScriptDirectory.from_config(single_cfg)
                core_heads = list(single_script.get_heads() or ())

                if len(core_heads) > 1:
                    logger.error(f"CONFLICT detected in {path}!")
                    logger.error(f"Found multiple heads: {core_heads}")
                    has_errors = True
                elif len(core_heads) == 1:
                    logger.info(f"OK: {path} (Head: {core_heads[0]})")
                continue

            module_label = os.path.basename(os.path.dirname(path))
            combined_locations = os.pathsep.join([core_migrations, path])
            single_cfg = _get_alembic_config(combined_locations)
            single_script = ScriptDirectory.from_config(single_cfg)

            module_head_revs = list(
                single_script.get_revisions(f"{module_label}@head") or ()
            )

            if len(module_head_revs) > 1:
                logger.error(f"CONFLICT detected in {path}!")
                logger.error(
                    f"Found multiple heads for branch '{module_label}': "
                    f"{[r.revision for r in module_head_revs]}"
                )
                has_errors = True
            elif len(module_head_revs) == 1:
                logger.info(
                    f"OK: {path} (Branch: {module_label}, Head: {module_head_revs[0].revision})"
                )
            else:
                pass

        except Exception as e:
            logger.warning(f"Could not check {path}: {e}")

    if has_errors:
        logger.error("Migration validation failed! Please resolve conflicts.")
        sys.exit(1)

    logger.info("All modules have linear migration history.")

