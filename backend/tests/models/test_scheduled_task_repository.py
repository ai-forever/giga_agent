import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.scheduled_task import (
    KIND_CRON,
    STATUS_PENDING,
    STATUS_RUNNING,
    ScheduledTaskRepository,
)
from giga_agent.models.users import User


def _utc(offset_seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


class ScheduledTaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_claim_due_respects_time_and_enabled(self) -> None:
        owner = await self._user("a@example.com")
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            due = await repo.create(
                owner_id=owner.id,
                name="due",
                prompt="p",
                run_at=_utc(-60),
            )
            await repo.create(
                owner_id=owner.id,
                name="future",
                prompt="p",
                run_at=_utc(3600),
            )
            await repo.create(
                owner_id=owner.id,
                name="disabled",
                prompt="p",
                run_at=_utc(-60),
                is_enabled=False,
            )

        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            claimed = await repo.claim_due(datetime.now(timezone.utc))
            self.assertEqual([t.id for t in claimed], [due.id])
            self.assertEqual(claimed[0].status, STATUS_RUNNING)

        # Already-running tasks are not re-claimed.
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            again = await repo.claim_due(datetime.now(timezone.utc))
            self.assertEqual(again, [])

    async def test_concurrent_claim_assigns_task_once(self) -> None:
        # A shared file-based SQLite DB so two connections see the same rows
        # (an ``:memory:`` DB is private per connection).
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{path}",
            connect_args={"timeout": 30},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with factory() as session:
                user = User(email="race@example.com", hashed_password="h", is_active=True)
                session.add(user)
                await session.commit()
                await session.refresh(user)
                repo = ScheduledTaskRepository(session)
                task = await repo.create(
                    owner_id=user.id,
                    name="race",
                    prompt="p",
                    run_at=_utc(-60),
                )
                task_id = task.id

            async def claim_once() -> list:
                async with factory() as session:
                    return await ScheduledTaskRepository(session).claim_due(
                        datetime.now(timezone.utc)
                    )

            results = await asyncio.gather(claim_once(), claim_once())
            claimed = [t.id for batch in results for t in batch]
            # The task is handed to exactly one of the two concurrent claimers.
            self.assertEqual(claimed, [task_id])
        finally:
            await engine.dispose()
            os.unlink(path)

    async def test_reschedule_cron_and_reset_stale(self) -> None:
        owner = await self._user("b@example.com")
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(
                owner_id=owner.id,
                name="cron",
                prompt="p",
                kind=KIND_CRON,
                cron="*/5 * * * *",
                run_at=_utc(-60),
            )
            await repo.mark_status(task, STATUS_RUNNING)
            next_run = _utc(300)
            await repo.reschedule_cron(task, next_run, last_error=None)
            self.assertEqual(task.status, STATUS_PENDING)
            self.assertIsNone(task.last_result)

        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            stuck = await repo.create(
                owner_id=owner.id, name="stuck", prompt="p", run_at=_utc(-60)
            )
            await repo.mark_status(stuck, STATUS_RUNNING)
            count = await repo.reset_stale_running()
            self.assertGreaterEqual(count, 1)
            refreshed = await repo.get_by_id(stuck.id)
            self.assertEqual(refreshed.status, STATUS_PENDING)

    async def test_default_recipients_resolution(self) -> None:
        owner = await self._user("c@example.com")
        async with self.session_factory() as session:
            chan = ChannelBotRepository(session)
            bot = await chan.create(user_id=owner.id, channel_type="telegram")

            approved_default = await chan.upsert_contact(
                bot_id=bot.id, external_chat_id="100"
            )
            await chan.set_contact_fields_by_external_id(
                bot_id=bot.id,
                external_chat_id="100",
                is_approved=True,
                is_default_task_recipient=True,
            )
            # approved but not default
            await chan.upsert_contact(bot_id=bot.id, external_chat_id="200")
            await chan.set_contact_fields_by_external_id(
                bot_id=bot.id, external_chat_id="200", is_approved=True
            )
            # default but not approved
            await chan.upsert_contact(bot_id=bot.id, external_chat_id="300")
            await chan.set_contact_fields_by_external_id(
                bot_id=bot.id,
                external_chat_id="300",
                is_default_task_recipient=True,
            )

            defaults = await chan.list_default_recipients_for_owner(owner.id)
            self.assertEqual([c.id for c in defaults], [approved_default.id])


if __name__ == "__main__":
    unittest.main()
