"""Exercises the core_oauth_connections migration backfill on SQLite.

The risk the plan flagged: on SQLite the ``Uuid`` column stores a 32-char hex
string without dashes, but the runtime provider key is ``f"mcp:{uuid}"``
(dashed). The migration backfills in Python so the key is normalized — this test
proves a stored MCP token maps to the canonical dashed ``mcp:<uuid>`` key.
"""

import importlib.util
import tempfile
import unittest
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "giga_agent"
    / "models"
    / "migrations"
    / "2026_06_24_1200-5e7c3b1a9f00_add_oauth_connections.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig_oauth", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_old_table(conn: sa.Connection) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE core_mcp_oauth_tokens (
            id CHAR(32) NOT NULL PRIMARY KEY,
            user_id CHAR(32) NOT NULL,
            server_id CHAR(32) NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            expires_at DATETIME,
            token_type VARCHAR(64),
            scope TEXT,
            client_id TEXT,
            client_secret TEXT,
            created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
            updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL
        )
        """
    )
    for col in ("id", "user_id", "server_id"):
        conn.exec_driver_sql(
            f"CREATE INDEX ix_core_mcp_oauth_tokens_{col} "
            f"ON core_mcp_oauth_tokens ({col})"
        )


class MigrationBackfillTests(unittest.TestCase):
    def test_upgrade_backfills_dashed_mcp_key(self) -> None:
        migration = _load_migration()
        user_id = uuid.uuid4()
        server_id = uuid.uuid4()
        # SQLAlchemy stores Uuid as 32 hex chars (no dashes) on sqlite.
        user_hex = user_id.hex
        server_hex = server_id.hex

        with tempfile.TemporaryDirectory() as tmp:
            engine = sa.create_engine(f"sqlite:///{Path(tmp) / 'm.sqlite'}")
            with engine.begin() as conn:
                _create_old_table(conn)
                conn.exec_driver_sql(
                    "INSERT INTO core_mcp_oauth_tokens "
                    "(id, user_id, server_id, access_token, refresh_token, scope) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user_hex, server_hex, "acc", "ref", "read"),
                )

                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    migration.upgrade()

                rows = conn.exec_driver_sql(
                    "SELECT user_id, provider_key, access_token, refresh_token, scope "
                    "FROM core_oauth_connections"
                ).fetchall()

            engine.dispose()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[1], f"mcp:{server_id}")  # dashed canonical form
        self.assertEqual(row[2], "acc")
        self.assertEqual(row[3], "ref")
        self.assertEqual(row[4], "read")

    def test_old_table_dropped(self) -> None:
        migration = _load_migration()
        with tempfile.TemporaryDirectory() as tmp:
            engine = sa.create_engine(f"sqlite:///{Path(tmp) / 'm.sqlite'}")
            with engine.begin() as conn:
                _create_old_table(conn)
                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    migration.upgrade()
                names = {
                    r[0]
                    for r in conn.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            engine.dispose()
        self.assertIn("core_oauth_connections", names)
        self.assertNotIn("core_mcp_oauth_tokens", names)


if __name__ == "__main__":
    unittest.main()
