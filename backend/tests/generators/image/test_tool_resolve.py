import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from giga_agent.generators.image.tool import _resolve_generator


class ImageToolResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_generator_delegates_to_resolver(self):
        fake_generator = object()
        resolver = MagicMock()
        resolver.has_image_generator = True
        resolver.get_image_generator = AsyncMock(return_value=fake_generator)
        runtime = types.SimpleNamespace(config={"configurable": {}})

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ) as mocked_from_config:
            resolved = await _resolve_generator(runtime)

        mocked_from_config.assert_called_once_with(runtime.config)
        resolver.get_image_generator.assert_awaited_once_with()
        self.assertIs(resolved, fake_generator)

    async def test_resolve_generator_raises_when_generator_not_selected(self):
        resolver = MagicMock()
        resolver.has_image_generator = False
        resolver.get_image_generator = AsyncMock()
        runtime = types.SimpleNamespace(config={"configurable": {}})

        with patch(
            "giga_agent.core.agent.runtime_resolver.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            with self.assertRaisesRegex(ValueError, "не выбран генератор"):
                await _resolve_generator(runtime)

        resolver.get_image_generator.assert_not_awaited()
