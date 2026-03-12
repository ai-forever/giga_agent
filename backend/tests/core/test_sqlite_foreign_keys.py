import unittest
from unittest.mock import patch

from sqlalchemy import text

from giga_agent.core.db import dispose_engine, get_engine


class SQLiteForeignKeysTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await dispose_engine()

    async def test_get_engine_enables_sqlite_foreign_keys(self) -> None:
        with patch(
            "giga_agent.core.db.get_db_url",
            return_value="sqlite+aiosqlite:///:memory:",
        ):
            engine = await get_engine()

            async with engine.connect() as connection:
                pragma_result = await connection.execute(text("PRAGMA foreign_keys"))

            self.assertEqual(pragma_result.scalar_one(), 1)
