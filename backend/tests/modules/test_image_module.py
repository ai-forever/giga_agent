import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.grok.generator import GrokImagineImageGen
from giga_agent.generators.image.nano_banana.generator import NanoBananaImageGen
from langchain.tools import tool

from giga_agent.modules.image import ImageModule


@tool
def provider_image_tool(prompt: str) -> str:
    """Provider-specific image generation tool stub."""
    return prompt


class _RuntimeStub:
    @classmethod
    def get_tools(cls):
        return [provider_image_tool]


class ImageModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_disabled_without_current_generator(self):
        module = ImageModule()
        user = types.SimpleNamespace(image_generator_id=None)

        tools = await module.get_tools(user=user, agent=object())
        instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_enabled_with_current_generator(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_image_generator=True,
            get_image_generator=AsyncMock(return_value=_RuntimeStub()),
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
        self.assertEqual(tools[0].name, "provider_image_tool")
        self.assertIsNotNone(instructions)
        self.assertIn("gen_image", instructions)

    async def test_module_returns_no_tools_for_invalid_generator_ref(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_image_generator=False,
            get_image_generator=AsyncMock(),
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

    async def test_module_exposes_grok_specific_tool(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_image_generator=True,
            get_image_generator=AsyncMock(
                return_value=GrokImagineImageGen(api_key="test-key")
            ),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)

        tool_names = {tool.name for tool in tools}
        self.assertIn("gen_image", tool_names)
        self.assertEqual(tool_names, {"gen_image"})

    async def test_module_exposes_nano_banana_specific_tool(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        config = {"configurable": {}}
        resolver = types.SimpleNamespace(
            has_image_generator=True,
            get_image_generator=AsyncMock(
                return_value=NanoBananaImageGen(api_key="test-key")
            ),
        )

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            tools = await module.get_tools(user=user, agent=object(), config=config)

        tool_names = {tool.name for tool in tools}
        self.assertIn("gen_image", tool_names)
        self.assertEqual(tool_names, {"gen_image"})
