import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import giga_agent.scheduled.runner as runner
from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.scheduled_task import (
    KIND_CRON,
    STATUS_DONE,
    STATUS_PENDING,
    ScheduledTaskRepository,
)
from giga_agent.models.users import User


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def deliver(self, bot, external_chat_id, parts, *, token, external_user_id=None):
        self.calls.append((bot.id, external_chat_id, external_user_id, tuple(parts)))
        return True


class RunnerDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(Base.metadata.create_all)

        self.fake_runtime = FakeRuntime()

        async def _fake_get_runtime(channel_type, settings):
            return self.fake_runtime

        self._orig_get_runtime = runner.ChannelRegistry.get_runtime
        runner.ChannelRegistry.get_runtime = staticmethod(_fake_get_runtime)

    async def asyncTearDown(self) -> None:
        runner.ChannelRegistry.get_runtime = self._orig_get_runtime
        await self.engine.dispose()

    async def _user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(email=email, hashed_password="h", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_explicit_targets_delivered(self) -> None:
        owner = await self._user("o@example.com")
        async with self.session_factory() as session:
            chan = ChannelBotRepository(session)
            bot = await chan.create(user_id=owner.id, channel_type="telegram")
            targets = [{"bot_id": str(bot.id), "external_chat_id": "42"}]
            delivered, failed = await runner._deliver_to_targets(
                chan,
                owner_id=owner.id,
                targets=targets,
                parts=[{"kind": "text", "value": "hi"}],
                token="t",
            )
        self.assertEqual((delivered, failed), (1, 0))
        self.assertEqual(self.fake_runtime.calls[0][1], "42")

    async def test_target_not_owned_counts_as_failed(self) -> None:
        owner = await self._user("o2@example.com")
        other = await self._user("other@example.com")
        async with self.session_factory() as session:
            chan = ChannelBotRepository(session)
            foreign_bot = await chan.create(user_id=other.id, channel_type="telegram")
            targets = [{"bot_id": str(foreign_bot.id), "external_chat_id": "1"}]
            delivered, failed = await runner._deliver_to_targets(
                chan,
                owner_id=owner.id,
                targets=targets,
                parts=[{"kind": "text", "value": "x"}],
                token="t",
            )
        self.assertEqual((delivered, failed), (0, 1))
        self.assertEqual(self.fake_runtime.calls, [])

    async def test_finalize_once_is_terminal(self) -> None:
        owner = await self._user("o3@example.com")
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(
                owner_id=owner.id,
                name="once",
                prompt="p",
                run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            await runner._finalize(repo, task, STATUS_DONE)
            refreshed = await repo.get_by_id(task.id)
            self.assertEqual(refreshed.status, STATUS_DONE)

    async def test_finalize_cron_reschedules(self) -> None:
        owner = await self._user("o4@example.com")
        async with self.session_factory() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(
                owner_id=owner.id,
                name="cron",
                prompt="p",
                kind=KIND_CRON,
                cron="*/5 * * * *",
                run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            await runner._finalize(repo, task, STATUS_DONE)
            refreshed = await repo.get_by_id(task.id)
            self.assertEqual(refreshed.status, STATUS_PENDING)
            # SQLite returns naive datetimes; normalize to UTC for comparison.
            next_run = refreshed.run_at
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            self.assertGreater(next_run, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
