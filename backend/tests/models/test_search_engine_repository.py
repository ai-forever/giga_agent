import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import User


class SearchEngineRepositoryTests(unittest.IsolatedAsyncioTestCase):
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
        user = await self._create_user("search1@example.com")

        async with self.session_factory() as session:
            repo = SearchEngineRepository(session)
            created = await repo.create(
                owner_id=user.id,
                engine_type="tavily",
                name="main",
                settings={"api_key": "tvly-key"},
                is_active=True,
            )
            self.assertEqual(created.type, "tavily")

            found = await repo.get_by_owner_and_type(user.id, "tavily")
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.id, created.id)

            updated = await repo.update(
                found,
                name="updated",
                settings={"api_key": "tvly-key-2"},
            )
            self.assertEqual(updated.name, "updated")
            self.assertEqual(updated.settings, {"api_key": "tvly-key-2"})

            await repo.delete(updated)
            deleted = await repo.get_by_id(updated.id)
            self.assertIsNone(deleted)

    async def test_cache_roundtrip(self) -> None:
        user = await self._create_user("search2@example.com")

        async with self.session_factory() as session:
            repo = SearchEngineRepository(session)
            created = await repo.create(
                owner_id=user.id,
                engine_type="tavily",
                settings={"api_key": "tvly-key"},
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

            key = SearchEngineRepository.cache_key(created.id)
            self.assertTrue(key.startswith("search_engine:ctx:"))

    async def test_get_by_owner_only_active(self) -> None:
        user = await self._create_user("search3@example.com")

        async with self.session_factory() as session:
            repo = SearchEngineRepository(session)
            await repo.create(
                owner_id=user.id,
                engine_type="tavily",
                name="active",
                is_active=True,
                settings={"api_key": "tvly-key"},
            )
            await repo.create(
                owner_id=user.id,
                engine_type="tavily",
                name="inactive",
                is_active=False,
                settings={"api_key": "tvly-key"},
            )

            all_engines = await repo.get_by_owner(user.id, only_active=False)
            active_engines = await repo.get_by_owner(user.id, only_active=True)
            self.assertEqual(len(all_engines), 2)
            self.assertEqual(len(active_engines), 1)

    async def test_delete_cleans_resource_permissions(self) -> None:
        owner = await self._create_user("search-owner-delete@example.com")
        viewer = await self._create_user("search-viewer-delete@example.com")

        async with self.session_factory() as session:
            repo = SearchEngineRepository(session)
            engine = await repo.create(
                owner_id=owner.id,
                engine_type="tavily",
                settings={"api_key": "tvly-key"},
                is_active=True,
            )
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="search_engine",
                resource_id=engine.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            await repo.delete(engine)
            acl = await permissions.list_permissions_for_resource(
                resource_type="search_engine",
                resource_id=engine.id,
            )

        self.assertEqual(acl, [])
