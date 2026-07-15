import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.embedding import EmbeddingRepository
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.resource_permission import (
    PermissionGrantItem,
    ResourcePermissionRepository,
)
from giga_agent.models.search_engine import SearchEngineRepository
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

    async def test_delete_cleans_resource_permissions_for_connector_and_children(
        self,
    ) -> None:
        owner = await self._create_user("connector-owner-delete@example.com")
        viewer = await self._create_user("connector-viewer-delete@example.com")

        async with self.session_factory() as session:
            connector_repo = ConnectorRepository(session)
            connector = await connector_repo.create(
                owner_id=owner.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )
            llm = await LLMRepository(session).create(
                owner_id=owner.id,
                llm_type="openai",
                connector_id=connector.id,
                model_id="gpt-4o-mini",
                settings={},
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
            image_generator = await ImageGeneratorRepository(session).create(
                owner_id=owner.id,
                generator_type="openai",
                connector_id=connector.id,
                settings={},
                is_active=True,
            )
            search_engine = await SearchEngineRepository(session).create(
                owner_id=owner.id,
                engine_type="tavily",
                connector_id=connector.id,
                settings={"api_key": "tvly-key"},
                is_active=True,
            )

            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permissions(
                items=[
                    PermissionGrantItem(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        owner_type="user",
                        owner_id=viewer.id,
                        permission="read",
                    )
                    for resource_type, resource_id in (
                        (
                            "connector",
                            connector.id,
                        ),
                        (
                            "llm",
                            llm.id,
                        ),
                        (
                            "embedding",
                            embedding.id,
                        ),
                        (
                            "image_generator",
                            image_generator.id,
                        ),
                        (
                            "search_engine",
                            search_engine.id,
                        ),
                    )
                ]
            )

            await connector_repo.delete(connector)

            connector_acl = await permissions.list_permissions_for_resource(
                resource_type="connector",
                resource_id=connector.id,
            )
            llm_acl = await permissions.list_permissions_for_resource(
                resource_type="llm",
                resource_id=llm.id,
            )
            embedding_acl = await permissions.list_permissions_for_resource(
                resource_type="embedding",
                resource_id=embedding.id,
            )
            image_generator_acl = await permissions.list_permissions_for_resource(
                resource_type="image_generator",
                resource_id=image_generator.id,
            )
            search_engine_acl = await permissions.list_permissions_for_resource(
                resource_type="search_engine",
                resource_id=search_engine.id,
            )

        self.assertEqual(connector_acl, [])
        self.assertEqual(llm_acl, [])
        self.assertEqual(embedding_acl, [])
        self.assertEqual(image_generator_acl, [])
        self.assertEqual(search_engine_acl, [])
