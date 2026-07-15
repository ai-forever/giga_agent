from __future__ import annotations

import os
from typing import Annotated

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging
from giga_agent.core.migrations import MigrationScope, get_module_migration_scope

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


def _scope_has_tables(base, target_prefix: str) -> bool:
    return any(
        table_name.startswith(target_prefix) for table_name in base.metadata.tables
    )


def _module_config(scope: MigrationScope, db_url: str | None):
    cfg = _get_alembic_config(
        os.pathsep.join(scope.version_locations), scope.version_table
    )
    if db_url:
        cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
    return cfg


def _module_head_for_revision(scope: MigrationScope, db_url: str | None) -> str:
    from alembic.script import ScriptDirectory

    cfg = _module_config(scope, db_url)
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads() or ())
    if len(heads) > 1:
        logger.error(
            "Module '%s' migrations have multiple heads: %s", scope.scope_id, heads
        )
        raise typer.Exit(code=1)
    return heads[0] if heads else "base"


def makemigrations(
    agent_path: Annotated[
        str,
        typer.Argument(help="Path to agent instance, e.g. giga_agent.agents.run:agent"),
    ] = "giga_agent.agents.run:agent",
    core: Annotated[
        bool,
        typer.Option(
            "--core",
            help=(
                "Generate migration for core models (giga_agent.models). "
                "Intended for library developers; prefer `make core-migrations`."
            ),
        ),
    ] = False,
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
    empty: Annotated[
        bool,
        typer.Option(
            "--empty",
            help=(
                "If set and a single module_path is provided, create an empty migration "
                "when no schema changes are detected for that module."
            ),
        ),
    ] = False,
) -> None:
    """
    Creates a new migration for a module (or for all modules of the agent).
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    reset_settings_cache()
    setup_cli_logging("INFO")

    if core and module_path is not None:
        logger.error("--core cannot be combined with module_path.")
        raise typer.Exit(code=2)

    if empty and module_path is None and not core:
        logger.error(
            "--empty can only be used when module_path is provided (or with --core)."
        )
        raise typer.Exit(code=2)

    logger.info(f"Loading agent from {agent_path}...")
    try:
        agent = load_agent_from_string(agent_path)
    except Exception:
        logger.exception("Failed to load agent")
        typer.secho("Failed to load agent. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    selected_modules = []
    normalized_input_import: str | None = None

    if core:
        selected_modules = []
    elif module_path is not None:
        normalized_input_import = _normalize_module_import_path(module_path)
        for mod in agent.all_modules:
            if _get_agent_module_import(mod) == normalized_input_import:
                selected_modules = [mod]
                break

        if not selected_modules:
            logger.error(
                f"Module '{module_path}' not found among loaded agent modules."
            )
            logger.info("Available modules (import -> id -> path):")
            for mod in agent.all_modules:
                logger.info(
                    f" - {_get_agent_module_import(mod)} -> {getattr(mod, 'id', '?')} -> {mod.module_path}"
                )
            raise typer.Exit(code=1)
    else:
        selected_modules = list(agent.all_modules)

    db_url = get_db_url()
    if db_url:
        wait_for_db(db_url)

    try:
        from giga_agent.core.db import Base
    except Exception:
        logger.exception("Could not import giga_agent.core.db.Base")
        typer.secho("Could not import Base. Traceback:", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        import giga_agent.models  # noqa: F401
    except Exception:
        logger.warning(
            "Could not import giga_agent.models before migration generation."
        )

    core_migrations = _get_core_models_migration_path()
    if core and not os.path.exists(core_migrations):
        logger.info(f"Creating core migrations directory: {core_migrations}")
        os.makedirs(core_migrations, exist_ok=True)

    core_cfg = None
    if os.path.exists(core_migrations):
        core_cfg = _get_alembic_config(core_migrations, "alembic_version")
        if db_url:
            core_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
        check_db_is_up_to_date(core_cfg, scope_label="core")

    if core:
        logger.warning(
            "Generating core migration via `giga_agent makemigrations --core` is intended for "
            "library developers. Prefer `make core-migrations` for the canonical workflow."
        )
        if not message.strip():
            logger.warning(
                "Core migration message is empty; consider passing -m/--message."
            )

        alembic_cfg = core_cfg
        if alembic_cfg is None:
            logger.error("Core migrations directory is not available.")
            raise typer.Exit(code=1)

        alembic_cfg.cmd_opts = type("CmdOpts", (), {"x": ["target_prefix=core_"]})()
        core_script = ScriptDirectory.from_config(alembic_cfg)
        core_heads = list(core_script.get_heads() or ())
        if len(core_heads) > 1:
            logger.error("Core migrations have multiple heads: %s", core_heads)
            raise typer.Exit(code=1)
        core_head_for_revision = core_heads[0] if core_heads else "base"

        created = False

        def _process_revision_directives(context, revision, directives) -> None:  # noqa: ANN001
            nonlocal created
            if not directives:
                return

            script = directives[0]
            upgrade_ops = getattr(script, "upgrade_ops", None)
            downgrade_ops = getattr(script, "downgrade_ops", None)

            is_empty = False
            if upgrade_ops is not None and hasattr(upgrade_ops, "is_empty"):
                try:
                    is_empty = bool(upgrade_ops.is_empty())
                    if downgrade_ops is not None and hasattr(downgrade_ops, "is_empty"):
                        is_empty = is_empty and bool(downgrade_ops.is_empty())
                except Exception:
                    is_empty = False

            if is_empty and not empty:
                directives[:] = []
                created = False
            else:
                created = True

        command.revision(
            alembic_cfg,
            message=message.strip() or None,
            autogenerate=True,
            head=core_head_for_revision,
            version_path=core_migrations,
            process_revision_directives=_process_revision_directives,
        )

        if created:
            logger.info(f"Migration created in {core_migrations}")
            return

        if empty:
            command.revision(
                alembic_cfg,
                message=message.strip() or None,
                autogenerate=False,
                head=core_head_for_revision,
                version_path=core_migrations,
            )
            logger.info(f"Empty migration created in {core_migrations}")
            return

        logger.info("No core schema changes detected; skipping.")
        return

    generated_any = False

    for mod in selected_modules:
        mod_import = _get_agent_module_import(mod)
        _, target_prefix = _get_module_name_and_prefix(mod_import)
        message_for_module = message.strip() or None
        force_empty_for_module = empty and normalized_input_import is not None

        try:
            module_models = mod.get_models()
            if not module_models:
                if force_empty_for_module:
                    logger.error(
                        f"Cannot create migration for module {getattr(mod, 'id', '?')} "
                        f"({mod_import}): no models declared via get_models()."
                    )
                    raise typer.Exit(code=1)
                continue

            scope = get_module_migration_scope(mod)
            if not os.path.exists(scope.migration_path):
                logger.info(f"Creating migrations directory: {scope.migration_path}")
                os.makedirs(scope.migration_path, exist_ok=True)

            module_cfg = _module_config(scope, db_url)
            check_db_is_up_to_date(
                module_cfg,
                scope_label=scope.scope_id,
                target_prefix=scope.target_prefix,
            )

            revision_head = _module_head_for_revision(scope, db_url)

            has_tables = _scope_has_tables(Base, target_prefix)
            if not has_tables:
                if force_empty_for_module:
                    logger.info(
                        f"Creating empty migration for module {getattr(mod, 'id', '?')} "
                        f"({mod_import}): no tables found with prefix '{target_prefix}'."
                    )
                    command.revision(
                        module_cfg,
                        message=message_for_module,
                        autogenerate=False,
                        head=revision_head,
                        version_path=scope.migration_path,
                    )
                    generated_any = True
                else:
                    logger.warning(
                        f"Skipping module {getattr(mod, 'id', '?')} ({mod_import}): "
                        f"no tables found with prefix '{target_prefix}' after get_models()."
                    )
                continue

            logger.info(
                f"Generating migration for module {getattr(mod, 'id', '?')} ({mod_import})"
            )
            logger.info(f"Target directory: {scope.migration_path}")
            logger.info(f"Filtering tables with prefix: {target_prefix}")

            module_cfg.cmd_opts = type(
                "CmdOpts", (), {"x": [f"target_prefix={target_prefix}"]}
            )()

            created = False

            def _process_revision_directives(context, revision, directives) -> None:  # noqa: ANN001
                nonlocal created
                if not directives:
                    return

                script = directives[0]
                upgrade_ops = getattr(script, "upgrade_ops", None)
                downgrade_ops = getattr(script, "downgrade_ops", None)

                is_empty = False
                if upgrade_ops is not None and hasattr(upgrade_ops, "is_empty"):
                    try:
                        is_empty = bool(upgrade_ops.is_empty())
                        if downgrade_ops is not None and hasattr(
                            downgrade_ops, "is_empty"
                        ):
                            is_empty = is_empty and bool(downgrade_ops.is_empty())
                    except Exception:
                        is_empty = False

                if is_empty:
                    directives[:] = []
                    created = False
                else:
                    created = True

            command.revision(
                module_cfg,
                message=message_for_module,
                autogenerate=True,
                head=revision_head,
                version_path=scope.migration_path,
                process_revision_directives=_process_revision_directives,
            )

            if created:
                generated_any = True
                logger.info(f"Migration created in {scope.migration_path}")
            elif force_empty_for_module:
                command.revision(
                    module_cfg,
                    message=message_for_module,
                    autogenerate=False,
                    head=revision_head,
                    version_path=scope.migration_path,
                )
                generated_any = True
                logger.info(f"Empty migration created in {scope.migration_path}")
            else:
                logger.info(
                    f"No schema changes detected for module {getattr(mod, 'id', '?')} "
                    f"({mod_import}); skipping."
                )
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
            logger.warning(
                "No module migrations were generated (no changes detected, or no models found)."
            )
        else:
            logger.warning(
                f"No migration generated for {normalized_input_import} "
                "(no changes detected, or no models found)."
            )
