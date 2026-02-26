import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.users import User


class ConnectorRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(
                email=email,
                hashed_password="hash",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_create_update_delete(self) -> None:
        user = await self._create_user("connector1@example.com")

        async with self.session_factory() as session:
            repo = ConnectorRepository(session)
            created = await repo.create(
                owner_id=user.id,
                connector_type="openai",
                name="main",
                settings={"api_key": "sk-test"},
                is_active=True,
            )
            self.assertEqual(created.type, "openai")

            updated = await repo.update(
                created,
                name="updated",
                settings={"api_key": "sk-test-2"},
            )
            self.assertEqual(updated.name, "updated")
            self.assertEqual(updated.settings, {"api_key": "sk-test-2"})

            await repo.delete(updated)
            deleted = await repo.get_by_id(updated.id)
            self.assertIsNone(deleted)

    async def test_cache_roundtrip(self) -> None:
        user = await self._create_user("connector2@example.com")

        async with self.session_factory() as session:
            repo = ConnectorRepository(session)
            created = await repo.create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
            )

            await repo.invalidate_cache(created.id)
            cached_before = await repo.get_from_cache(created.id)
            self.assertIsNone(cached_before)

            response = await repo.get_by_id_response(created.id, use_cache=True)
            self.assertIsNotNone(response)

            cached_after = await repo.get_from_cache(created.id)
            self.assertIsNotNone(cached_after)
            assert cached_after is not None
            self.assertEqual(cached_after.id, created.id)

            key = ConnectorRepository.cache_key(created.id)
            self.assertTrue(key.startswith("connector:ctx:"))
