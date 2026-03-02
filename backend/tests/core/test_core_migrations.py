import types
import unittest
from unittest.mock import Mock, patch

from giga_agent.core.migrations import apply_migrations


class CoreMigrationsTests(unittest.TestCase):
    def test_apply_migrations_uses_custom_target(self):
        agent = types.SimpleNamespace(all_modules=[])
        alembic_cfg = Mock()
        alembic_cfg.set_section_config = Mock(return_value=None)

        with patch(
            "giga_agent.core.migrations._get_core_models_migration_path",
            return_value="/tmp/core_migrations",
        ), patch(
            "giga_agent.core.migrations.os.path.exists",
            side_effect=lambda p: p == "/tmp/core_migrations",
        ), patch(
            "giga_agent.core.migrations.get_db_url",
            return_value="sqlite+aiosqlite:////tmp/test.db",
        ), patch(
            "giga_agent.core.migrations._get_alembic_config",
            return_value=alembic_cfg,
        ), patch(
            "giga_agent.core.migrations.wait_for_db"
        ) as wait_for_db, patch(
            "giga_agent.core.migrations.command.upgrade"
        ) as upgrade:
            apply_migrations(agent, target="head")

        wait_for_db.assert_called_once()
        upgrade.assert_called_once_with(alembic_cfg, "head")

    def test_apply_migrations_uses_heads_by_default(self):
        agent = types.SimpleNamespace(all_modules=[])
        alembic_cfg = Mock()
        alembic_cfg.set_section_config = Mock(return_value=None)

        with patch(
            "giga_agent.core.migrations._get_core_models_migration_path",
            return_value="/tmp/core_migrations",
        ), patch(
            "giga_agent.core.migrations.os.path.exists",
            side_effect=lambda p: p == "/tmp/core_migrations",
        ), patch(
            "giga_agent.core.migrations.get_db_url",
            return_value="sqlite+aiosqlite:////tmp/test.db",
        ), patch(
            "giga_agent.core.migrations._get_alembic_config",
            return_value=alembic_cfg,
        ), patch(
            "giga_agent.core.migrations.wait_for_db"
        ), patch(
            "giga_agent.core.migrations.command.upgrade"
        ) as upgrade:
            apply_migrations(agent)

        upgrade.assert_called_once_with(alembic_cfg, "heads")
