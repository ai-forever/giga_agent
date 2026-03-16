import unittest
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.file import FileRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.sandbox import SandboxProvider
from giga_agent.models.users import User


class FileRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
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

    async def _create_provider(self, owner_id: uuid.UUID, provider_type: str) -> SandboxProvider:
        async with self.session_factory() as session:
            provider = SandboxProvider(
                owner_id=owner_id,
                type=provider_type,
                settings={},
                idle_timeout=300,
                is_active=True,
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)
            return provider

    async def test_create_and_get_by_owner_provider_path(self) -> None:
        user = await self._create_user("u1@example.com")
        provider = await self._create_provider(user.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            created = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/home/user/bucket/report.txt",
                original_name="report.txt",
                file_type="text",
                size=123,
            )
            self.assertIsNotNone(created)

            found = await repo.get_by_owner_provider_path(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/home/user/bucket/report.txt",
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.id, created.id)

    async def test_duplicate_path_returns_none(self) -> None:
        user = await self._create_user("u2@example.com")
        provider = await self._create_provider(user.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            first = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/same/path.txt",
                original_name="path.txt",
                file_type="text",
                size=1,
            )
            second = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/same/path.txt",
                original_name="path.txt",
                file_type="text",
                size=1,
            )

            self.assertIsNotNone(first)
            self.assertIsNone(second)

    async def test_same_path_allowed_for_different_owner_or_provider(self) -> None:
        owner1 = await self._create_user("u3@example.com")
        owner2 = await self._create_user("u4@example.com")
        provider1_owner1 = await self._create_provider(owner1.id, "e2b")
        provider2_owner1 = await self._create_provider(owner1.id, "local_docker")
        provider_owner2 = await self._create_provider(owner2.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file1 = await repo.create(
                owner_id=owner1.id,
                provider_id=provider1_owner1.id,
                sandbox_path="/shared/path.txt",
                original_name="path.txt",
                file_type="text",
                size=1,
            )
            file2 = await repo.create(
                owner_id=owner1.id,
                provider_id=provider2_owner1.id,
                sandbox_path="/shared/path.txt",
                original_name="path.txt",
                file_type="text",
                size=1,
            )
            file3 = await repo.create(
                owner_id=owner2.id,
                provider_id=provider_owner2.id,
                sandbox_path="/shared/path.txt",
                original_name="path.txt",
                file_type="text",
                size=1,
            )

            self.assertIsNotNone(file1)
            self.assertIsNotNone(file2)
            self.assertIsNotNone(file3)

    async def test_delete_file(self) -> None:
        user = await self._create_user("u5@example.com")
        provider = await self._create_provider(user.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            created = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/to/delete.txt",
                original_name="to_delete.txt",
                file_type="text",
                size=10,
            )
            self.assertIsNotNone(created)

            await repo.delete(created)

            found = await repo.get_by_id(created.id)
            self.assertIsNone(found)

    async def test_get_by_owner_path(self) -> None:
        user = await self._create_user("u6@example.com")
        provider = await self._create_provider(user.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            created = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/lookup/by/path.txt",
                original_name="path.txt",
                file_type="text",
                size=17,
            )
            self.assertIsNotNone(created)

            found = await repo.get_by_owner_path(
                owner_id=user.id,
                sandbox_path="/lookup/by/path.txt",
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.id, created.id)

    async def test_delete_cleans_resource_permissions(self) -> None:
        owner = await self._create_user("u7@example.com")
        viewer = await self._create_user("u8@example.com")
        provider = await self._create_provider(owner.id, "e2b")

        async with self.session_factory() as session:
            repo = FileRepository(session)
            created = await repo.create(
                owner_id=owner.id,
                provider_id=provider.id,
                sandbox_path="/to/delete-acl.txt",
                original_name="to_delete_acl.txt",
                file_type="text",
                size=10,
            )
            self.assertIsNotNone(created)
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="file",
                resource_id=created.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            await repo.delete(created)
            acl = await permissions.list_permissions_for_resource(
                resource_type="file",
                resource_id=created.id,
            )

        self.assertEqual(acl, [])
