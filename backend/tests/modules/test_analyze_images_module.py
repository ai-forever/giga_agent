import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.modules.analyze_images import AnalyzeImagesModule


class AnalyzeImagesModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_disabled_without_llm_id(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=None)

        tools = await module.get_tools(user=user, agent=object())
        instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_disabled_when_runtime_cannot_analyze_image(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=uuid.uuid4())

        @asynccontextmanager
        async def _session_context():
            yield object()

        llm_runtime = types.SimpleNamespace(can_analyze_image=lambda: False)

        with patch(
            "giga_agent.modules.analyze_images.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.module.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_enabled_when_runtime_can_analyze_image(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=uuid.uuid4())

        @asynccontextmanager
        async def _session_context():
            yield object()

        llm_runtime = types.SimpleNamespace(can_analyze_image=lambda: True)

        with patch(
            "giga_agent.modules.analyze_images.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.analyze_images.module.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "analyze_image")
        self.assertIn("analyze_image", instructions)
