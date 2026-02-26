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

    Examples:
        uv run giga_agent makemigrations giga_agent.agents.run:agent --core -m "add core table"
        uv run giga_agent makemigrations giga_agent.agents.run:agent giga_agent.modules.auth -m "add auth"
        uv run giga_agent makemigrations giga_agent.agents.run:agent
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
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
        for mod in agent.modules:
            if _get_agent_module_import(mod) == normalized_input_import:
                selected_modules = [mod]
                break

        if not selected_modules:
            logger.error(
                f"Module '{module_path}' not found among loaded agent modules."
            )
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
    if core and not os.path.exists(core_migrations):
        logger.info(f"Creating core migrations directory: {core_migrations}")
        os.makedirs(core_migrations, exist_ok=True)

    if os.path.exists(core_migrations):
        migration_paths.append(core_migrations)

    for mod in agent.modules:
        if getattr(mod, "migration_path", None):
            migration_paths.append(mod.migration_path)

    version_locations = os.pathsep.join(migration_paths)

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

    # Ensure core + module models are imported so tables are visible in Base.metadata.
    try:
        import giga_agent.models  # noqa: F401
    except Exception:
        logger.warning(
            "Could not import giga_agent.models before migration generation."
        )

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

    if core:
        logger.warning(
            "Generating core migration via `giga_agent makemigrations --core` is intended for "
            "library developers. Prefer `make core-migrations` for the canonical workflow."
        )
        if not message.strip():
            logger.warning(
                "Core migration message is empty; consider passing -m/--message."
            )

        target_migration_dir = core_migrations
        target_prefix = "core_"

        alembic_cfg.cmd_opts = type(
            "CmdOpts", (), {"x": [f"target_prefix={target_prefix}"]}
        )()

        core_head_for_revision = core_head or "base"

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
            version_path=target_migration_dir,
            process_revision_directives=_process_revision_directives,
        )

        if created:
            logger.info(f"Migration created in {target_migration_dir}")
            return

        if empty:
            command.revision(
                alembic_cfg,
                message=message.strip() or None,
                autogenerate=False,
                head=core_head_for_revision,
                version_path=target_migration_dir,
            )
            logger.info(f"Empty migration created in {target_migration_dir}")
            return

        logger.info("No core schema changes detected; skipping.")
        return

    generated_any = False

    for mod in selected_modules:
        mod_import = _get_agent_module_import(mod)
        module_name, target_prefix = _get_module_name_and_prefix(mod_import)

        message_for_module = message.strip() or None

        try:
            module_depends_on: str | None = None
            module_branch_label: str = module_name
            revision_head: str = "base"
            revision_branch_label: str | None = None

            # Load models (if provided) to register tables in Base.metadata for autogenerate.
            module_models = mod.get_models()
            force_empty_for_module = empty and normalized_input_import is not None

            if not module_models:
                if force_empty_for_module:
                    logger.error(
                        f"Cannot create migration for module {getattr(mod, 'id', '?')} "
                        f"({mod_import}): no models declared via get_models()."
                    )
                    raise typer.Exit(code=1)
                continue

            target_migration_dir = os.path.join(mod.module_path, "migrations")
            if not os.path.exists(target_migration_dir):
                logger.info(f"Creating migrations directory: {target_migration_dir}")
                os.makedirs(target_migration_dir, exist_ok=True)

            if target_migration_dir not in migration_paths:
                migration_paths.append(target_migration_dir)
                alembic_cfg.set_main_option(
                    "version_locations", os.pathsep.join(migration_paths)
                )

            # Determine module head (for depends_on) using the same semantics as `giga_agent check`,
            # i.e. via "<branch_label>@head" in a script that includes core + this module.
            try:
                combined = os.pathsep.join(
                    [
                        p
                        for p in [
                            core_migrations
                            if os.path.exists(core_migrations)
                            else None,
                            target_migration_dir,
                        ]
                        if p
                    ]
                )
                module_cfg = _get_alembic_config(combined)
                if db_url:
                    module_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
                module_script = ScriptDirectory.from_config(module_cfg)

                module_head_revs = list(
                    module_script.get_revisions(f"{module_branch_label}@head") or ()
                )
                if len(module_head_revs) > 1:
                    logger.error(
                        f"Module '{module_name}' migrations have multiple heads: "
                        f"{[r.revision for r in module_head_revs]}"
                    )
                    raise typer.Exit(code=1)

                if len(module_head_revs) == 1:
                    # Subsequent module revisions don't declare a branch label again and should
                    # build on top of the current branch head.
                    module_depends_on = core_head
                    revision_head = module_head_revs[0].revision
                    revision_branch_label = None
                else:
                    module_depends_on = core_head
                    revision_head = "base"
                    revision_branch_label = module_branch_label
            except typer.Exit:
                raise
            except Exception as e:
                logger.warning(
                    f"Could not determine module head for depends_on ({module_name}): {e}"
                )
                module_depends_on = core_head
                revision_head = "base"
                # Be conservative: only assign a branch label if the directory appears empty.
                try:
                    existing_py = [
                        f
                        for f in os.listdir(target_migration_dir)
                        if f.endswith(".py") and not f.startswith("__")
                    ]
                except Exception:
                    existing_py = []
                revision_branch_label = module_branch_label if not existing_py else None

            has_tables = any(
                table_name.startswith(target_prefix)
                for table_name in Base.metadata.tables
            )
            if not has_tables:
                if force_empty_for_module:
                    logger.info(
                        f"Creating empty migration for module {getattr(mod, 'id', '?')} "
                        f"({mod_import}): no tables found with prefix '{target_prefix}'."
                    )
                    empty_message = message_for_module
                    revision_kwargs = {
                        "message": empty_message,
                        "autogenerate": False,
                        "head": revision_head,
                        "depends_on": module_depends_on,
                        "version_path": target_migration_dir,
                    }
                    if revision_branch_label is not None:
                        revision_kwargs["branch_label"] = revision_branch_label
                    command.revision(alembic_cfg, **revision_kwargs)
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
            logger.info(f"Target directory: {target_migration_dir}")
            logger.info(f"Filtering tables with prefix: {target_prefix}")

            alembic_cfg.cmd_opts = type(
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
                        # If we can't reliably detect emptiness, err on the side of creating.
                        is_empty = False

                if is_empty:
                    # Prevent creating a "no-op" revision unless explicitly requested via --empty.
                    directives[:] = []
                    created = False
                else:
                    created = True

            revision_kwargs = {
                "message": message_for_module,
                "autogenerate": True,
                "head": revision_head,
                "depends_on": module_depends_on,
                "version_path": target_migration_dir,
                "process_revision_directives": _process_revision_directives,
            }
            if revision_branch_label is not None:
                revision_kwargs["branch_label"] = revision_branch_label
            command.revision(alembic_cfg, **revision_kwargs)

            if created:
                generated_any = True
                logger.info(f"Migration created in {target_migration_dir}")
            else:
                if force_empty_for_module:
                    empty_message = message_for_module
                    revision_kwargs = {
                        "message": empty_message,
                        "autogenerate": False,
                        "head": revision_head,
                        "depends_on": module_depends_on,
                        "version_path": target_migration_dir,
                    }
                    if revision_branch_label is not None:
                        revision_kwargs["branch_label"] = revision_branch_label
                    command.revision(alembic_cfg, **revision_kwargs)
                    generated_any = True
                    logger.info(f"Empty migration created in {target_migration_dir}")
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
