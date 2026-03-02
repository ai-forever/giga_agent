import os
import unittest
from unittest.mock import patch, AsyncMock

from giga_agent.core.agent.base import BaseAgent


class BaseAgentSecretKeyRequirementTests(unittest.TestCase):
    async def test_raises_when_secret_key_env_is_missing(self):
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
            with self.assertRaises(Exception) as exc:
                agent = BaseAgent(modules=[], tools=[])
                async with agent.app.router.lifespan_context(agent.app):
                    pass

        self.assertEqual(
            str(exc.exception),
            "GIGA_AGENT_SECRET_KEY is not set. Please set env secret key.",
        )
