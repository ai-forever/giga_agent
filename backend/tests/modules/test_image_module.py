import types
import unittest
import uuid
from contextlib import asynccontextmanager
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
        record = types.SimpleNamespace(
            id=user.image_generator_id,
            owner_id=user.id,
            type="openai",
            is_active=True,
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.image.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRegistry.get",
            return_value=_RuntimeStub,
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "provider_image_tool")
        self.assertIsNotNone(instructions)
        self.assertIn("gen_image", instructions)

    async def test_module_returns_no_tools_for_invalid_generator_ref(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.image.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            tools = await module.get_tools(user=user, agent=object())
            instructions = await module.get_instructions(user=user, agent=object())

        self.assertEqual(tools, [])
        self.assertIsNone(instructions)

    async def test_module_exposes_grok_specific_tool(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        record = types.SimpleNamespace(
            id=user.image_generator_id,
            owner_id=user.id,
            type="grok_imagine",
            is_active=True,
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.image.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRegistry.get",
            return_value=GrokImagineImageGen,
        ):
            tools = await module.get_tools(user=user, agent=object())

        tool_names = {tool.name for tool in tools}
        self.assertIn("gen_image", tool_names)
        self.assertEqual(tool_names, {"gen_image"})

    async def test_module_exposes_nano_banana_specific_tool(self):
        module = ImageModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), image_generator_id=uuid.uuid4())
        record = types.SimpleNamespace(
            id=user.image_generator_id,
            owner_id=user.id,
            type="nano_banana",
            is_active=True,
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        with patch(
            "giga_agent.modules.image.module.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRepository.get_cached_or_db",
            AsyncMock(return_value=record),
        ), patch(
            "giga_agent.modules.image.module.ImageGeneratorRegistry.get",
            return_value=NanoBananaImageGen,
        ):
            tools = await module.get_tools(user=user, agent=object())

        tool_names = {tool.name for tool in tools}
        self.assertIn("gen_image", tool_names)
        self.assertEqual(tool_names, {"gen_image"})
