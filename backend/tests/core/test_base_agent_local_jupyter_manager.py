import os
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.core.agent.base import BaseAgent


class BaseAgentLocalJupyterManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_stops_local_jupyter_manager_on_shutdown(self):
        manager = type("ManagerStub", (), {"stop": AsyncMock(return_value=None)})()
        channel_manager = type(
            "ChannelManagerStub",
            (),
            {
                "start_all": AsyncMock(return_value=None),
                "stop_all": AsyncMock(return_value=None),
            },
        )()

        with patch.dict(
            os.environ,
            {"GIGA_AGENT_SECRET_KEY": "secret"},
            clear=False,
        ), patch(
            "giga_agent.sandbox.local_jupyter.manager.get_local_jupyter_server_manager",
            return_value=manager,
        ), patch.object(
            BaseAgent,
            "run_startup_migrations",
            AsyncMock(return_value=None),
        ), patch.object(
            BaseAgent,
            "run_startup_hooks",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.vectorstores.qdrant.shutdown_qdrant_client",
            AsyncMock(return_value=None),
        ), patch(
            "giga_agent.channels.manager.get_channel_manager",
            return_value=channel_manager,
        ):
            agent = BaseAgent(modules=[], tools=[])
            async with agent.app.router.lifespan_context(agent.app):
                pass

        channel_manager.start_all.assert_awaited_once()
        channel_manager.stop_all.assert_awaited_once()
        manager.stop.assert_awaited_once()
