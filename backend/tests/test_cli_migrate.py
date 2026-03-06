import unittest
from unittest.mock import patch

import typer

from giga_agent.cli.commands.migrate import migrate


class CLIMigrateTests(unittest.TestCase):
    def test_migrate_uses_heads_by_default(self):
        agent = object()
        with patch(
            "giga_agent.cli.commands.migrate.load_agent_from_string",
            return_value=agent,
        ), patch(
            "giga_agent.cli.commands.migrate.apply_migrations"
        ) as apply_migrations:
            migrate()

        apply_migrations.assert_called_once_with(agent, target="heads")

    def test_migrate_uses_custom_target(self):
        agent = object()
        with patch(
            "giga_agent.cli.commands.migrate.load_agent_from_string",
            return_value=agent,
        ), patch(
            "giga_agent.cli.commands.migrate.apply_migrations"
        ) as apply_migrations:
            migrate("base")

        apply_migrations.assert_called_once_with(agent, target="base")

    def test_migrate_returns_exit_1_on_error(self):
        with patch(
            "giga_agent.cli.commands.migrate.load_agent_from_string",
            return_value=object(),
        ), patch(
            "giga_agent.cli.commands.migrate.apply_migrations",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(typer.Exit) as exc:
                migrate()

        self.assertEqual(exc.exception.exit_code, 1)
