from __future__ import annotations

import unittest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.agent import (
    AgentConnectorBinding,
    AgentMcpBinding,
    AgentProfileCreate,
    AgentProfileRepository,
    AgentSkillBinding,
)
from giga_agent.models.users import User
from giga_agent.models.mcp_server import McpServer


class AgentProfileRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session_factory() as session:
            user = User(
                email="agents@example.com",
                hashed_password="hash",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            self.user_id = user.id

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_custom_profile_bindings_and_delete_do_not_delete_dependencies(
        self,
    ) -> None:
        async with self.session_factory() as session:
            repository = AgentProfileRepository(session)
            profile = await repository.create_custom(
                self.user_id,
                AgentProfileCreate(
                    name="Researcher",
                    description="Researches",
                    prompt="Do research",
                    modules=["search"],
                    is_enabled=False,
                ),
            )
            await repository.replace_bindings(
                profile.id,
                skills=[{"requirement_name": "report-writing"}],
                connectors=[{"catalog_id": "github"}],
            )
            self.assertEqual(len(await repository.skill_bindings(profile.id)), 1)
            self.assertEqual(len(await repository.connector_bindings(profile.id)), 1)

            await repository.delete(profile)

            skill_count = await session.scalar(
                select(func.count()).select_from(AgentSkillBinding)
            )
            connector_count = await session.scalar(
                select(func.count()).select_from(AgentConnectorBinding)
            )
            self.assertEqual(skill_count, 0)
            self.assertEqual(connector_count, 0)

    async def test_builtin_override_is_idempotent_per_owner_and_ref(self) -> None:
        async with self.session_factory() as session:
            repository = AgentProfileRepository(session)
            first = await repository.ensure_builtin_override(
                self.user_id, "builtin:subagents:researcher"
            )
            second = await repository.ensure_builtin_override(
                self.user_id, "builtin:subagents:researcher"
            )
            self.assertEqual(first.id, second.id)
            self.assertEqual(first.source, "builtin_override")

    async def test_custom_bindings_store_direct_mcp_ids(self) -> None:
        async with self.session_factory() as session:
            repository = AgentProfileRepository(session)
            server = McpServer(
                owner_id=self.user_id,
                name="GitHub MCP",
                url="https://mcp.example.com",
                is_active=True,
            )
            session.add(server)
            await session.commit()
            await session.refresh(server)
            profile = await repository.create_custom(
                self.user_id,
                AgentProfileCreate(
                    name="MCP researcher",
                    description="Researches",
                    prompt="Use MCP",
                    modules=["search"],
                ),
            )

            await repository.replace_custom_bindings(
                profile.id,
                skills=[
                    {
                        "requirement_name": "runtime-skill",
                        "skill_id": None,
                    }
                ],
                mcp_server_ids=[server.id, server.id],
            )

            bindings = await repository.mcp_bindings(profile.id)
            self.assertEqual([item.mcp_server_id for item in bindings], [server.id])
            skill_bindings = await repository.skill_bindings(profile.id)
            self.assertEqual(skill_bindings[0].requirement_name, "runtime-skill")

            await repository.delete(profile)
            self.assertEqual(
                await session.scalar(
                    select(func.count()).select_from(AgentMcpBinding)
                ),
                0,
            )
