import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import User


class RagCollectionsRepositoryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_delete_cleans_resource_permissions(self) -> None:
        owner = await self._create_user("rag-owner-delete@example.com")
        viewer = await self._create_user("rag-viewer-delete@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=owner.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )
            embedding = await EmbeddingRepository(session).create(
                owner_id=owner.id,
                embedding_type="openai",
                connector_id=connector.id,
                model_id="text-embedding-3-small",
                vector_size=1536,
                settings={},
                is_active=True,
            )
            repo = RagCollectionsRepository(session)
            collection = await repo.create(
                owner_id=owner.id,
                name="docs",
                embedding_id=embedding.id,
            )
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="rag_collection",
                resource_id=collection.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            deleted = await repo.delete(owner_id=owner.id, collection_id=collection.id)
            acl = await permissions.list_permissions_for_resource(
                resource_type="rag_collection",
                resource_id=collection.id,
            )

        self.assertTrue(deleted)
        self.assertEqual(acl, [])
