import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.modules.analyze_images import AnalyzeImagesModule


class AnalyzeImagesModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_disabled_without_llm_id(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=None)

        # No config -> no resolver -> module is disabled.
        tools = await module.get_tools(user=user, agent=object())
        instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_disabled_when_runtime_cannot_analyze_image(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_llm=True,
            get_llm_runtime=AsyncMock(
                return_value=types.SimpleNamespace(can_analyze_image=lambda: False)
            ),
            has_fast_llm=False,
            get_fast_llm_runtime=AsyncMock(),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)
            instructions = await module.get_instructions(
                user=user, agent=object(), config=config
            )

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_enabled_when_runtime_can_analyze_image(self):
        module = AnalyzeImagesModule()
        user = types.SimpleNamespace(llm_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_llm=True,
            get_llm_runtime=AsyncMock(
                return_value=types.SimpleNamespace(can_analyze_image=lambda: True)
            ),
            has_fast_llm=False,
            get_fast_llm_runtime=AsyncMock(),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)
            instructions = await module.get_instructions(
                user=user, agent=object(), config=config
            )

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "analyze_image")
        self.assertIn("analyze_image", instructions)
