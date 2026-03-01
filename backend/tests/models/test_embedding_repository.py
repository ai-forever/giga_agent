import unittest
import uuid

from cashews import cache
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import User


class EmbeddingRepositoryTests(unittest.IsolatedAsyncioTestCase):
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
        embedding_id = uuid.uuid4()
        await cache.set(EmbeddingRepository.cache_key(embedding_id), {"x": 1}, expire="5m")

        await EmbeddingRepository.invalidate_cache(embedding_id)

        self.assertIsNone(await cache.get(EmbeddingRepository.cache_key(embedding_id)))

    async def test_get_cached_or_db_returns_embedding_context(self):
        user = await self._create_user("embedding1@example.com")

        async with self.session_factory() as session:
            connector_repo = ConnectorRepository(session)
            connector = await connector_repo.create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )

            embedding_repo = EmbeddingRepository(session)
            embedding = await embedding_repo.create(
                owner_id=user.id,
                embedding_type="openai",
                connector_id=connector.id,
                model_id="text-embedding-3-small",
                vector_size=512,
                settings={"dimensions": 512},
                is_active=True,
            )

            ctx = await embedding_repo.get_by_id_context(embedding.id, use_cache=False)

        assert ctx is not None
        self.assertEqual(ctx.id, embedding.id)
        self.assertEqual(ctx.type, "openai")
        self.assertEqual(ctx.model_id, "text-embedding-3-small")
        self.assertEqual(ctx.vector_size, 512)
        self.assertEqual(ctx.settings, {"dimensions": 512})

        cached = await cache.get(EmbeddingRepository.cache_key(embedding.id))
        self.assertIsNotNone(cached)

    async def test_delete_cleans_resource_permissions(self):
        owner = await self._create_user("embedding-owner-delete@example.com")
        viewer = await self._create_user("embedding-viewer-delete@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=owner.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )

            embedding_repo = EmbeddingRepository(session)
            embedding = await embedding_repo.create(
                owner_id=owner.id,
                embedding_type="openai",
                connector_id=connector.id,
                model_id="text-embedding-3-small",
                vector_size=512,
                settings={},
                is_active=True,
            )
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="embedding",
                resource_id=embedding.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            await embedding_repo.delete(embedding)
            acl = await permissions.list_permissions_for_resource(
                resource_type="embedding",
                resource_id=embedding.id,
            )

        self.assertEqual(acl, [])
