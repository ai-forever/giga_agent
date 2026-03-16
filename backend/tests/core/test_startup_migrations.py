import os
import types
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import giga_agent.core.agent.base as base_module
from giga_agent.core.agent.base import BaseAgent


class StartupMigrationsTests(unittest.IsolatedAsyncioTestCase):
    def _build_agent(self) -> BaseAgent:
        return BaseAgent(modules=[], tools=[])

    async def test_lifespan_runs_migrations_before_startup_hooks(self):
        with patch.dict(
            os.environ, {"GIGA_AGENT_SECRET_KEY": "test-secret"}, clear=False
        ):
            agent = self._build_agent()
            call_order: list[str] = []

            async def _run_migrations(*_args, **_kwargs):
                call_order.append("migrations")

            async def _run_hooks(*_args, **_kwargs):
                call_order.append("hooks")

            with patch.object(
                BaseAgent,
                "run_startup_migrations",
                AsyncMock(side_effect=_run_migrations),
            ) as run_migrations, patch.object(
                BaseAgent, "run_startup_hooks", AsyncMock(side_effect=_run_hooks)
            ) as run_hooks:
                async with agent.app.router.lifespan_context(agent.app):
                    pass

            run_migrations.assert_awaited_once()
            run_hooks.assert_awaited_once()
            self.assertEqual(call_order, ["migrations", "hooks"])

    async def test_lifespan_fails_fast_when_migrations_fail(self):
        agent = self._build_agent()

        with patch.dict(
            os.environ, {"GIGA_AGENT_SECRET_KEY": "test-secret"}, clear=False
        ):
            with patch.object(
                BaseAgent,
                "run_startup_migrations",
                AsyncMock(side_effect=RuntimeError("boom")),
            ), patch.object(BaseAgent, "run_startup_hooks", AsyncMock()) as run_hooks:
                with self.assertRaises(RuntimeError):
                    async with agent.app.router.lifespan_context(agent.app):
                        pass

        run_hooks.assert_not_awaited()

    async def test_run_startup_migrations_respects_skip_flag(self):
        agent = self._build_agent()
        settings = types.SimpleNamespace(
            giga_agent_skip_startup_migrations=True,
            giga_agent_runtime="local",
            giga_agent_startup_migrations_lock_key="startup:migrations:lock",
            giga_agent_startup_migrations_lock_ttl_sec=1800,
        )

        with patch(
            "giga_agent.core.agent.base.get_settings", return_value=settings
        ), patch("giga_agent.core.agent.base.cache.lock") as lock, patch(
            "giga_agent.core.agent.base.asyncio.to_thread", AsyncMock()
        ) as to_thread:
            await agent.run_startup_migrations()

        lock.assert_not_called()
        to_thread.assert_not_awaited()

    async def test_run_startup_migrations_uses_lock_and_to_thread(self):
        agent = self._build_agent()
        settings = types.SimpleNamespace(
            giga_agent_skip_startup_migrations=False,
            giga_agent_runtime="local",
            giga_agent_startup_migrations_lock_key="startup:migrations:lock",
            giga_agent_startup_migrations_lock_ttl_sec=1800,
        )
        lock_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        @asynccontextmanager
        async def _lock_context(*args, **kwargs):
            lock_calls.append((args, kwargs))
            yield

        lock_mock = Mock(side_effect=_lock_context)
        to_thread = AsyncMock()

        with patch(
            "giga_agent.core.agent.base.get_settings", return_value=settings
        ), patch("giga_agent.core.agent.base.cache.lock", lock_mock), patch(
            "giga_agent.core.agent.base.asyncio.to_thread", to_thread
        ):
            await agent.run_startup_migrations()

        self.assertEqual(len(lock_calls), 1)
        lock_args, lock_kwargs = lock_calls[0]
        self.assertEqual(lock_args, ("startup:migrations:lock",))
        self.assertEqual(lock_kwargs, {"expire": 1800, "wait": True})
        to_thread.assert_awaited_once_with(base_module.apply_migrations, agent)
