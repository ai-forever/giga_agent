import types
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.project import ProjectRepository
from giga_agent.modules.projects.module import ProjectsModule


class ProjectsModuleInstructionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.owner_id = uuid.uuid4()
        async with self.session_factory() as session:
            repo = ProjectRepository(session)
            self.project = await repo.create(
                owner_id=self.owner_id,
                name="alpha",
                instructions="Always answer in Russian.",
            )

        self.user = types.SimpleNamespace(id=self.owner_id)
        self.module = ProjectsModule()

        self._patcher = patch(
            "giga_agent.modules.projects.module.get_session_factory",
            new=self._fake_get_session_factory,
        )
        self._patcher.start()

    async def asyncTearDown(self) -> None:
        self._patcher.stop()
        await self.engine.dispose()

    async def _fake_get_session_factory(self):
        return self.session_factory

    async def _call(self, config):
        return await self.module.get_instructions(
            user=self.user, agent=None, state=None, config=config
        )

    async def test_returns_none_when_no_project_in_config(self):
        result = await self._call({"metadata": {}, "configurable": {}})
        self.assertIsNone(result)

    async def test_returns_instructions_when_project_in_metadata(self):
        result = await self._call(
            {"metadata": {"project_id": str(self.project.id)}}
        )
        self.assertIsNotNone(result)
        self.assertIn("alpha", result)
        self.assertIn("Always answer in Russian.", result)

    async def test_returns_instructions_when_project_in_configurable(self):
        result = await self._call(
            {"configurable": {"project_id": str(self.project.id)}}
        )
        self.assertIsNotNone(result)
        self.assertIn("Always answer in Russian.", result)

    async def test_returns_none_for_other_owner(self):
        other_user = types.SimpleNamespace(id=uuid.uuid4())
        result = await self.module.get_instructions(
            user=other_user,
            agent=None,
            state=None,
            config={"metadata": {"project_id": str(self.project.id)}},
        )
        self.assertIsNone(result)

    async def test_returns_none_for_invalid_project_id(self):
        result = await self._call({"metadata": {"project_id": "not-a-uuid"}})
        self.assertIsNone(result)

    async def test_returns_none_when_user_missing(self):
        result = await self.module.get_instructions(
            user=None,
            agent=None,
            state=None,
            config={"metadata": {"project_id": str(self.project.id)}},
        )
        self.assertIsNone(result)

    async def test_returns_none_when_project_has_no_instructions(self):
        async with self.session_factory() as session:
            repo = ProjectRepository(session)
            empty_project = await repo.create(
                owner_id=self.owner_id, name="empty"
            )
        result = await self._call(
            {"metadata": {"project_id": str(empty_project.id)}}
        )
        self.assertIsNone(result)
