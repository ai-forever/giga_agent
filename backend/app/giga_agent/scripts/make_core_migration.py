#!/usr/bin/env python
"""
Script for giga_agent library developers to create core model migrations.
This is NOT intended for end users - they should use `giga_agent makemigrations` for their modules.

Usage:
    python -m giga_agent.scripts.make_core_migration -m "migration message"
    
Or via Makefile:
    make core-migrations m="migration message"
"""
import os
import sys
import argparse

from alembic.config import Config
from alembic import command

# Ensure giga_agent package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from giga_agent.core.db import get_db_url
from giga_agent.core.logging import get_logger, setup_cli_logging

logger = get_logger(__name__)


def get_alembic_config(version_locations: str) -> Config:
    """
    Helper to create Alembic Config with dynamic version locations.
    """
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini_path = os.path.join(package_dir, "alembic.ini")
    
    if not os.path.exists(alembic_ini_path):
        raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")
    
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("version_locations", version_locations)
    return alembic_cfg


def make_core_migration(message: str = ""):
    """
    Creates a new migration for core models (giga_agent/models).
    """
    setup_cli_logging("INFO")
    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    
    # Import models to register them with Base.metadata
    # This is necessary for autogenerate to detect changes
    import giga_agent.models  # noqa: F401
    
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_migration_dir = os.path.join(package_dir, "models", "migrations")
    target_prefix = "core_"
    
    # Create migrations directory if it doesn't exist
    if not os.path.exists(target_migration_dir):
        logger.info(f"Creating migrations directory: {target_migration_dir}")
        os.makedirs(target_migration_dir)
    
    # Configure Alembic
    alembic_cfg = get_alembic_config(target_migration_dir)
    
    # Set DB URL
    db_url = get_db_url()
    if db_url:
        alembic_cfg.set_section_option("alembic", "sqlalchemy.url", db_url)
    
    logger.info("Generating migration for Core Models")
    logger.info(f"Target directory: {target_migration_dir}")
    logger.info(f"Filtering tables with prefix: {target_prefix}")
    
    # Pass target_prefix via x-arguments (available in env.py via context.get_x_argument)
    alembic_cfg.cmd_opts = type(
        "CmdOpts", (), {"x": [f"target_prefix={target_prefix}"]}
    )()
    
    try:
        command.revision(
            alembic_cfg,
            message=message,
            autogenerate=True,
            version_path=target_migration_dir,
        )
        logger.info(f"Migration created in {target_migration_dir}")
    except Exception as e:
        logger.error(f"Error creating migration: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Create migration for giga_agent core models"
    )
    parser.add_argument(
        "-m", "--message",
        default="",
        help="Migration message"
    )
    args = parser.parse_args()
    
    make_core_migration(message=args.message)


if __name__ == "__main__":
    main()
