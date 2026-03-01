import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.users import User


class ImageGeneratorRepositoryTests(unittest.IsolatedAsyncioTestCase):
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
        owner = await self._create_user("image-owner-delete@example.com")
        viewer = await self._create_user("image-viewer-delete@example.com")

        async with self.session_factory() as session:
            repo = ImageGeneratorRepository(session)
            generator = await repo.create(
                owner_id=owner.id,
                generator_type="fusion_brain",
                settings={"api_key": "key", "secret_key": "secret"},
                is_active=True,
            )
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="image_generator",
                resource_id=generator.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            await repo.delete(generator)
            acl = await permissions.list_permissions_for_resource(
                resource_type="image_generator",
                resource_id=generator.id,
            )

        self.assertEqual(acl, [])
