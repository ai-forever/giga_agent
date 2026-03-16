import types
import unittest
from unittest.mock import patch

from giga_agent.core.migrations import apply_migrations, get_module_migration_scope


class CoreMigrationsTests(unittest.TestCase):
    def test_apply_migrations_uses_custom_target_for_core_scope(self):
        agent = types.SimpleNamespace(all_modules=[])

        with patch(
            "giga_agent.core.migrations.get_core_migration_scope",
            return_value=types.SimpleNamespace(scope_id="core"),
        ), patch(
            "giga_agent.core.migrations.get_agent_migration_scopes",
            return_value=[types.SimpleNamespace(scope_id="core")],
        ), patch(
            "giga_agent.core.migrations.get_db_url",
            return_value="sqlite+aiosqlite:////tmp/test.db",
        ), patch(
            "giga_agent.core.migrations.wait_for_db"
        ) as wait_for_db, patch(
            "giga_agent.core.migrations.apply_scope_migrations"
        ) as apply_scope_migrations:
            apply_migrations(agent, target="head", requested_scope="core")

        wait_for_db.assert_called_once()
        apply_scope_migrations.assert_called_once_with(
            types.SimpleNamespace(scope_id="core"),
            target="head",
            db_url="sqlite+aiosqlite:////tmp/test.db",
        )

    def test_apply_migrations_uses_all_scopes_by_default(self):
        agent = types.SimpleNamespace(all_modules=[])
        core_scope = types.SimpleNamespace(scope_id="core")
        rag_scope = types.SimpleNamespace(scope_id="rag")

        with patch(
            "giga_agent.core.migrations.get_agent_migration_scopes",
            return_value=[core_scope, rag_scope],
        ), patch(
            "giga_agent.core.migrations.get_db_url",
            return_value="sqlite+aiosqlite:////tmp/test.db",
        ), patch(
            "giga_agent.core.migrations.wait_for_db"
        ), patch(
            "giga_agent.core.migrations.apply_scope_migrations"
        ) as apply_scope_migrations:
            apply_migrations(agent)

        self.assertEqual(
            apply_scope_migrations.call_args_list,
            [
                unittest.mock.call(
                    core_scope,
                    target="head",
                    db_url="sqlite+aiosqlite:////tmp/test.db",
                ),
                unittest.mock.call(
                    rag_scope,
                    target="head",
                    db_url="sqlite+aiosqlite:////tmp/test.db",
                ),
            ],
        )

    def test_apply_migrations_for_module_runs_only_module_scope(self):
        module = types.SimpleNamespace(id="rag", module_path="/tmp/rag")
        agent = types.SimpleNamespace(all_modules=[module])
        core_scope = types.SimpleNamespace(scope_id="core")
        rag_scope = types.SimpleNamespace(scope_id="rag")

        with patch(
            "giga_agent.core.migrations.get_agent_migration_scopes",
            return_value=[core_scope, rag_scope],
        ), patch(
            "giga_agent.core.migrations.get_db_url",
            return_value="sqlite+aiosqlite:////tmp/test.db",
        ), patch(
            "giga_agent.core.migrations.wait_for_db"
        ), patch(
            "giga_agent.core.migrations.apply_scope_migrations"
        ) as apply_scope_migrations:
            apply_migrations(agent, requested_scope="rag")

        self.assertEqual(
            apply_scope_migrations.call_args_list,
            [
                unittest.mock.call(
                    rag_scope,
                    target="head",
                    db_url="sqlite+aiosqlite:////tmp/test.db",
                ),
            ],
        )

    def test_module_scope_uses_module_id_for_version_table(self):
        class RagModule:
            __module__ = "giga_agent.modules.rag.module"

            def __init__(self):
                self.id = "rag"
                self.module_path = "/tmp/rag"

        module = RagModule()

        scope = get_module_migration_scope(module)

        self.assertEqual(scope.scope_id, "rag")
        self.assertEqual(scope.version_table, "alembic_version_rag")
        self.assertEqual(scope.target_prefix, "rag_")
