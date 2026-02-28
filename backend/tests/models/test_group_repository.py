import unittest
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.group import GroupMember, GroupRepository
from giga_agent.models.users import User


class GroupRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self, email: str, is_superuser: bool = False) -> User:
        async with self.session_factory() as session:
            user = User(
                email=email,
                hashed_password="hash",
                is_active=True,
                is_superuser=is_superuser,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_create_list_get_update_delete(self) -> None:
        owner = await self._create_user("owner@example.com")

        async with self.session_factory() as session:
            repo = GroupRepository(session)
            created = await repo.create(
                owner_id=owner.id,
                name="admins",
                description="Admin group",
                data={"scope": "all"},
                permissions={"role": "admin"},
            )
            self.assertEqual(created.name, "admins")

            listed = await repo.list_all()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].id, created.id)

            by_id = await repo.get_by_id(created.id)
            self.assertIsNotNone(by_id)
            assert by_id is not None
            self.assertEqual(by_id.id, created.id)

            updated = await repo.update(
                created,
                name="admins-updated",
                description="Updated",
                data={"scope": "core"},
            )
            self.assertEqual(updated.name, "admins-updated")
            self.assertEqual(updated.description, "Updated")
            self.assertEqual(updated.data, {"scope": "core"})

            await repo.delete(updated)
            deleted = await repo.get_by_id(updated.id)
            self.assertIsNone(deleted)

    async def test_add_users_get_users_and_group_ids(self) -> None:
        owner = await self._create_user("owner2@example.com")
        member_1 = await self._create_user("member1@example.com")
        member_2 = await self._create_user("member2@example.com")

        async with self.session_factory() as session:
            repo = GroupRepository(session)
            group = await repo.create(owner_id=owner.id, name="core-team")

            await repo.add_users(group.id, [member_1.id, member_2.id, member_2.id])

            users = await repo.get_group_users(group.id)
            user_ids = {user.id for user in users}
            self.assertEqual(user_ids, {member_1.id, member_2.id})

            member_1_group_ids = await repo.get_group_ids_by_user_id(member_1.id)
            self.assertEqual(member_1_group_ids, [group.id])

            removed = await repo.remove_user(group.id, member_1.id)
            self.assertTrue(removed)
            removed_again = await repo.remove_user(group.id, member_1.id)
            self.assertFalse(removed_again)

    async def test_add_users_atomic_strict(self) -> None:
        owner = await self._create_user("owner3@example.com")
        member = await self._create_user("member3@example.com")
        missing_user_id = uuid.uuid4()

        async with self.session_factory() as session:
            repo = GroupRepository(session)
            group = await repo.create(owner_id=owner.id, name="strict-team")

            with self.assertRaises(ValueError):
                await repo.add_users(group.id, [member.id, missing_user_id])

            users_after = await repo.get_group_users(group.id)
            self.assertEqual(users_after, [])

    async def test_delete_group_cascades_members(self) -> None:
        owner = await self._create_user("owner4@example.com")
        member = await self._create_user("member4@example.com")

        async with self.session_factory() as session:
            repo = GroupRepository(session)
            group = await repo.create(owner_id=owner.id, name="cascade-team")
            await repo.add_users(group.id, [member.id])

            await repo.delete(group)

            member_group_ids = await repo.get_group_ids_by_user_id(member.id)
            self.assertEqual(member_group_ids, [])

            memberships = await session.execute(select(GroupMember))
            self.assertEqual(list(memberships.scalars().all()), [])
