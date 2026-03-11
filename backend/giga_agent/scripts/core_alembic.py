#!/usr/bin/env python
"""
Script to run arbitrary Alembic commands with core migration settings.

Applies the same configuration as `make core-migrations`:
  - alembic.ini from the giga_agent package
  - version_locations = giga_agent/models/migrations
  - target_prefix = core_
  - auto-imports core models

Usage:
    python -m giga_agent.scripts.core_alembic upgrade head
    python -m giga_agent.scripts.core_alembic downgrade -1
    python -m giga_agent.scripts.core_alembic history
    python -m giga_agent.scripts.core_alembic current

Or via Makefile:
    make core-alembic args="upgrade head"
    make core-alembic args="history"
"""
import os
import sys
from importlib.resources import as_file, files

from alembic.config import Config, CommandLine

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from giga_agent.conf import reset_settings_cache
from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging

logger = get_logger(__name__)


class CoreAlembicCommandLine(CommandLine):
    """Alembic CommandLine subclass that injects core migration settings."""

    def main(self, argv=None):
        setup_cli_logging("INFO")
        os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
        reset_settings_cache()

        # Import core models so they register with Base.metadata
        import giga_agent.models  # noqa: F401

        options = self.parser.parse_args(argv)
        if not hasattr(options, "cmd"):
            self.parser.error("too few arguments")

        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_migration_dir = os.path.join(package_dir, "models", "migrations")
        if not os.path.exists(target_migration_dir):
            os.makedirs(target_migration_dir)

        alembic_ini_res = files("giga_agent").joinpath("alembic.ini")
        with as_file(alembic_ini_res) as alembic_ini_path:
            if not os.path.exists(alembic_ini_path):
                raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")

            cfg = Config(
                file_=str(alembic_ini_path),
                ini_section=options.name,
                cmd_opts=options,
            )
            cfg.set_main_option("version_locations", target_migration_dir)
            cfg.set_main_option("version_table", "alembic_version")

            # Set DB URL
            db_url = get_db_url()
            if db_url:
                cfg.set_section_option("alembic", "sqlalchemy.url", db_url)

            # Inject target_prefix so env.py filters tables correctly
            if not hasattr(options, "x") or options.x is None:
                options.x = []
            options.x.append("target_prefix=core_")

            self.run_cmd(cfg, options)


def main() -> None:
    CoreAlembicCommandLine(prog="core-alembic").main(argv=sys.argv[1:])


if __name__ == "__main__":
    main()
