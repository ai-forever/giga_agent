from __future__ import annotations

import os
from typing import Annotated

import typer

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging

from ..migrations.common import (
    _get_alembic_config,
    _get_agent_module_import,
    _get_core_models_migration_path,
    _get_module_name_and_prefix,
    _normalize_module_import_path,
    check_db_is_up_to_date,
    wait_for_db,
)
from ..utils.imports import load_agent_from_string

logger = get_logger(__name__)


def makemigrations(
    agent_path: Annotated[
        str, typer.Argument(help="Path to agent instance, e.g. agent.py:agent")
    ],
    module_path: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional module python import path (e.g. giga_agent.modules.auth). "
                "If omitted, migrations are generated for all modules enabled in the agent."
            )
        ),
    ] = None,
    message: Annotated[
        str,
        typer.Option(
            "-m",
            "--message",
            help=(
                "Migration message. Used only when generating for a single module. "
                "Ignored when module_path is omitted."
            ),
        ),
    ] = "",
) -> None:
    """
    Creates a new migration for a module (or for all modules of the agent).

    Examples:
        uv run giga_agent makemigrations agent_test/agent.py:agent giga_agent.modules.auth -m "add auth"
        uv run giga_agent makemigrations agent_test/agent.py:agent
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    setup_cli_logging("INFO")

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        typer.secho("Failed to load agent. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    selected_modules = []
    normalized_input_import: str | None = None

    if module_path is not None:
        normalized_input_import = _normalize_module_import_path(module_path)
        for mod in agent.modules:
            if _get_agent_module_import(mod) == normalized_input_import:
                selected_modules = [mod]
                break

        if not selected_modules:
            logger.error(f"Module '{module_path}' not found among loaded agent modules.")
            logger.info("Available modules (import -> id -> path):")
            for mod in agent.modules:
                logger.info(
                    f" - {_get_agent_module_import(mod)} -> {getattr(mod, 'id', '?')} -> {mod.module_path}"
                )
            raise typer.Exit(code=1)
    else:
        selected_modules = list(agent.modules)

    migration_paths: list[str] = []

    core_migrations = _get_core_models_migration_path()
    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    for mod in agent.modules:
        p = os.path.join(mod.module_path, "migrations")
        if os.path.exists(p):
            migration_paths.append(p)

    version_locations = " ".join(migration_paths)

    alembic_cfg = _get_alembic_config(version_locations)

    db_url = get_db_url()
    if db_url:
        alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
        wait_for_db(db_url)

    check_db_is_up_to_date(alembic_cfg)

    try:
        from giga_agent.core.db import Base
    except Exception:
        logger.exception("Could not import giga_agent.core.db.Base")
        typer.secho("Could not import Base. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    core_head: str | None = None
    try:
        if os.path.exists(core_migrations):
            core_cfg = _get_alembic_config(core_migrations)
            if db_url:
                core_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
            core_script = ScriptDirectory.from_config(core_cfg)
            core_heads = list(core_script.get_heads() or ())
            if len(core_heads) == 1:
                core_head = core_heads[0]
            elif len(core_heads) > 1:
                logger.error(f"Core migrations have multiple heads: {core_heads}")
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.warning(f"Could not determine core head for depends_on: {e}")

    generated_any = False

    for mod in selected_modules:
        mod_import = _get_agent_module_import(mod)
        module_name, target_prefix = _get_module_name_and_prefix(mod_import)

        module_models = mod.get_models()
        if not module_models:
            logger.info(
                f"Skipping module {getattr(mod, 'id', '?')} ({mod_import}): "
                "no models declared via get_models()."
            )
            continue

        has_tables = any(
            table_name.startswith(target_prefix) for table_name in Base.metadata.tables
        )
        if not has_tables:
            logger.warning(
                f"Skipping module {getattr(mod, 'id', '?')} ({mod_import}): "
                f"no tables found with prefix '{target_prefix}' after get_models()."
            )
            continue

        target_migration_dir = os.path.join(mod.module_path, "migrations")
        if not os.path.exists(target_migration_dir):
            logger.info(f"Creating migrations directory: {target_migration_dir}")
            os.makedirs(target_migration_dir)

        if target_migration_dir not in migration_paths:
            migration_paths.append(target_migration_dir)
            alembic_cfg.set_main_option("version_locations", " ".join(migration_paths))

        if normalized_input_import is None:
            message_for_module = f"autogen {module_name}"
        else:
            message_for_module = message or f"autogen {module_name}"

        logger.info(
            f"Generating migration for module {getattr(mod, 'id', '?')} ({mod_import})"
        )
        logger.info(f"Target directory: {target_migration_dir}")
        logger.info(f"Filtering tables with prefix: {target_prefix}")

        alembic_cfg.cmd_opts = type(
            "CmdOpts", (), {"x": [f"target_prefix={target_prefix}"]}
        )()

        try:
            module_depends_on: str | None = None
            module_branch_label: str | None = None
            try:
                module_cfg = _get_alembic_config(target_migration_dir)
                if db_url:
                    module_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
                module_script = ScriptDirectory.from_config(module_cfg)
                module_heads = list(module_script.get_heads() or ())
                if len(module_heads) > 1:
                    logger.error(
                        f"Module '{module_name}' migrations have multiple heads: {module_heads}"
                    )
                    raise typer.Exit(code=1)
                if module_heads:
                    module_depends_on = module_heads[0]
                else:
                    module_depends_on = core_head
                    module_branch_label = module_name
            except typer.Exit:
                raise
            except Exception as e:
                logger.warning(
                    f"Could not determine module head for depends_on ({module_name}): {e}"
                )
                module_depends_on = core_head
                module_branch_label = module_name

            command.revision(
                alembic_cfg,
                message=message_for_module,
                autogenerate=True,
                head="base",
                branch_label=module_branch_label,
                depends_on=module_depends_on,
                version_path=target_migration_dir,
            )
            generated_any = True
            logger.info(f"Migration created in {target_migration_dir}")
        except Exception:
            logger.exception(f"Error creating migration for {mod_import}")
            typer.secho(
                f"Error creating migration for {mod_import}. Traceback:",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

    if not generated_any:
        if normalized_input_import is None:
            logger.warning("No module migrations were generated (no module models found).")
        else:
            logger.warning(
                f"No migration generated for {normalized_input_import} (no module models found)."
            )

