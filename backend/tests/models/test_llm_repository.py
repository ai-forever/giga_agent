import unittest
import uuid

from cashews import cache
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.users import User


class LLMRepositoryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_invalidate_cache_removes_ctx_key(self):
        llm_id = uuid.uuid4()
        await cache.set(LLMRepository.cache_key(llm_id), {"x": 1}, expire="5m")

        await LLMRepository.invalidate_cache(llm_id)

        self.assertIsNone(await cache.get(LLMRepository.cache_key(llm_id)))

    async def test_get_cached_or_db_returns_llm_context(self):
        user = await self._create_user("llm1@example.com")

        async with self.session_factory() as session:
            connector_repo = ConnectorRepository(session)
            connector = await connector_repo.create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )

            llm_repo = LLMRepository(session)
            llm = await llm_repo.create(
                owner_id=user.id,
                llm_type="openai",
                connector_id=connector.id,
                model_id="gpt-4o-mini",
                settings={"temperature": 0.3},
                is_active=True,
            )

            ctx = await llm_repo.get_by_id_context(llm.id, use_cache=False)

        assert ctx is not None
        self.assertEqual(ctx.id, llm.id)
        self.assertEqual(ctx.type, "openai")
        self.assertEqual(ctx.model_id, "gpt-4o-mini")
        self.assertEqual(ctx.settings, {"temperature": 0.3})

        cached = await cache.get(LLMRepository.cache_key(llm.id))
        self.assertIsNotNone(cached)

    async def test_get_readable_for_user_includes_granted_llm(self):
        owner = await self._create_user("llm-owner@example.com")
        viewer = await self._create_user("llm-viewer@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=owner.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )
            llm_repo = LLMRepository(session)
            llm = await llm_repo.create(
                owner_id=owner.id,
                llm_type="openai",
                connector_id=connector.id,
                model_id="gpt-4o-mini",
                settings={},
                is_active=True,
            )
            await ResourcePermissionRepository(session).grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )
            readable = await llm_repo.get_readable_for_user(viewer.id)
            readable_by_id = await llm_repo.get_by_id_readable(
                llm.id,
                user_id=viewer.id,
            )

        self.assertEqual([item.id for item in readable], [llm.id])
        self.assertIsNotNone(readable_by_id)
        self.assertEqual(readable_by_id.id, llm.id)
