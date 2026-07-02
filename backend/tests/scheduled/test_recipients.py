import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.users import User
from giga_agent.modules.scheduler.tools import _resolve_targets


class RecipientResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(email=email, hashed_password="h", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_list_approved_and_resolve_targets(self) -> None:
        owner = await self._user("o@example.com")
        other = await self._user("x@example.com")
        async with self.session_factory() as session:
            chan = ChannelBotRepository(session)
            bot = await chan.create(user_id=owner.id, channel_type="telegram")
            c1 = await chan.upsert_contact(bot_id=bot.id, external_chat_id="11")
            await chan.set_contact_fields_by_external_id(
                bot_id=bot.id, external_chat_id="11", is_approved=True
            )
            await chan.upsert_contact(bot_id=bot.id, external_chat_id="22")  # not approved

            foreign_bot = await chan.create(user_id=other.id, channel_type="telegram")
            cf = await chan.upsert_contact(bot_id=foreign_bot.id, external_chat_id="99")
            await chan.set_contact_fields_by_external_id(
                bot_id=foreign_bot.id, external_chat_id="99", is_approved=True
            )

            approved = await chan.list_approved_contacts_for_owner(owner.id)
            self.assertEqual([c.id for c in approved], [c1.id])

            # Valid own contact resolves to a target.
            targets = await _resolve_targets(session, owner.id, [str(c1.id)])
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0]["external_chat_id"], "11")
            self.assertEqual(targets[0]["bot_id"], str(bot.id))

            # Foreign contact and garbage are ignored (owner-scoped).
            targets2 = await _resolve_targets(
                session, owner.id, [str(cf.id), "not-a-uuid"]
            )
            self.assertEqual(targets2, [])


if __name__ == "__main__":
    unittest.main()
