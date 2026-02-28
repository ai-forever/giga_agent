import unittest
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.group import GroupRepository
from giga_agent.models.llm import LLM
from giga_agent.models.llm import LLMRepository
from giga_agent.models.resource_permission import (
    ResourcePermission,
    ResourcePermissionRepository,
)
from giga_agent.models.users import User


class ResourcePermissionRepositoryTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_llm_for_owner(self, owner_id: uuid.UUID) -> LLM:
        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=owner_id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
                is_active=True,
            )
            llm = await LLMRepository(session).create(
                owner_id=owner_id,
                llm_type="openai",
                connector_id=connector.id,
                model_id="gpt-4o-mini",
                settings={},
                is_active=True,
            )
            return llm

    async def test_grant_permission_normalizes_and_is_idempotent(self):
        owner = await self._create_user("owner-grant@example.com")
        target = await self._create_user("target-grant@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            first = await repo.grant_permission(
                resource_type="LLM",
                resource_id=llm.id,
                owner_type="USER",
                owner_id=target.id,
                permission="Read",
            )
            second = await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="read",
            )

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.resource_type, "llm")
        self.assertEqual(first.owner_type, "user")
        self.assertEqual(first.owner_id, str(target.id))
        self.assertEqual(first.permission, "read")

    async def test_grant_permission_invalid_value_raises(self):
        owner = await self._create_user("owner-invalid@example.com")
        target = await self._create_user("target-invalid@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            with self.assertRaises(ValueError):
                await repo.grant_permission(
                    resource_type="unknown",
                    resource_id=llm.id,
                    owner_type="user",
                    owner_id=target.id,
                    permission="read",
                )

    async def test_revoke_permission(self):
        owner = await self._create_user("owner-revoke@example.com")
        target = await self._create_user("target-revoke@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="write",
            )
            removed = await repo.revoke_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="write",
            )
            removed_again = await repo.revoke_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="write",
            )

        self.assertTrue(removed)
        self.assertFalse(removed_again)

    async def test_public_permission_is_read_only_and_canonicalized(self):
        owner = await self._create_user("owner-public@example.com")
        outsider = await self._create_user("outsider-public@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            public_row = await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="group",
                owner_id="*",
                permission="read",
            )
            with self.assertRaises(ValueError):
                await repo.grant_permission(
                    resource_type="llm",
                    resource_id=llm.id,
                    owner_type="user",
                    owner_id="*",
                    permission="write",
                )
            can_public_read = await repo.has_access(
                user_id=outsider.id,
                resource_type="llm",
                resource_id=llm.id,
                permission="read",
            )
            can_public_write = await repo.has_access(
                user_id=outsider.id,
                resource_type="llm",
                resource_id=llm.id,
                permission="write",
            )

        self.assertEqual(public_row.owner_id, "*")
        self.assertEqual(public_row.owner_type, "user")
        self.assertTrue(can_public_read)
        self.assertFalse(can_public_write)

    async def test_list_permissions_for_resource_and_resources(self):
        owner = await self._create_user("owner-list@example.com")
        user_a = await self._create_user("user-a-list@example.com")
        user_b = await self._create_user("user-b-list@example.com")
        llm_a = await self._create_llm_for_owner(owner.id)
        llm_b = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm_a.id,
                owner_type="user",
                owner_id=user_a.id,
                permission="read",
            )
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm_b.id,
                owner_type="user",
                owner_id=user_b.id,
                permission="read",
            )
            only_a = await repo.list_permissions_for_resource(
                resource_type="llm",
                resource_id=llm_a.id,
            )
            both = await repo.list_permissions_for_resources(
                resource_type="llm",
                resource_ids=[llm_a.id, llm_b.id],
            )

        self.assertEqual(len(only_a), 1)
        self.assertEqual(only_a[0].resource_id, llm_a.id)
        self.assertEqual(len(both), 2)
        self.assertEqual({item.resource_id for item in both}, {llm_a.id, llm_b.id})

    async def test_has_access_owner_direct_write_and_group(self):
        owner = await self._create_user("owner-access@example.com")
        target = await self._create_user("target-access@example.com")
        member = await self._create_user("member-access@example.com")
        outsider = await self._create_user("outsider-access@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            group_repo = GroupRepository(session)
            group = await group_repo.create(
                owner_id=owner.id,
                name="acl-team",
                description=None,
            )
            await group_repo.add_users(group.id, [member.id])

            repo = ResourcePermissionRepository(session)
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="write",
            )
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="group",
                owner_id=group.id,
                permission="read",
            )

            self.assertTrue(
                await repo.has_access(
                    user_id=owner.id,
                    resource_type="llm",
                    resource_id=llm.id,
                    permission="write",
                )
            )
            self.assertTrue(
                await repo.has_access(
                    user_id=target.id,
                    resource_type="llm",
                    resource_id=llm.id,
                    permission="read",
                )
            )
            self.assertTrue(
                await repo.has_access(
                    user_id=member.id,
                    resource_type="llm",
                    resource_id=llm.id,
                    permission="read",
                )
            )
            self.assertFalse(
                await repo.has_access(
                    user_id=outsider.id,
                    resource_type="llm",
                    resource_id=llm.id,
                    permission="read",
                )
            )

    async def test_build_access_clause_filters_llms(self):
        owner = await self._create_user("owner-clause@example.com")
        viewer = await self._create_user("viewer-clause@example.com")
        llm_a = await self._create_llm_for_owner(owner.id)
        llm_b = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm_a.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )
            clause = await repo.build_access_clause(
                LLM,
                user_id=viewer.id,
                resource_type="llm",
                permission="read",
            )
            result = await session.execute(select(LLM.id).where(clause))
            ids = {row[0] for row in result.all()}
        self.assertEqual(ids, {llm_a.id})

    async def test_unique_constraint_prevents_duplicates(self):
        owner = await self._create_user("owner-uniq@example.com")
        target = await self._create_user("target-uniq@example.com")
        llm = await self._create_llm_for_owner(owner.id)

        async with self.session_factory() as session:
            repo = ResourcePermissionRepository(session)
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="read",
            )
            await repo.grant_permission(
                resource_type="llm",
                resource_id=llm.id,
                owner_type="user",
                owner_id=target.id,
                permission="read",
            )
            rows = await session.execute(select(ResourcePermission))

        self.assertEqual(len(list(rows.scalars().all())), 1)
