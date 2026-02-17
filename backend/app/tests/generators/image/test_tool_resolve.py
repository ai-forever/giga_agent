import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.generators.image.tool import _resolve_generator_for_user


class ImageToolResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_generator_delegates_to_manager(self):
        gen_id = uuid.uuid4()
        user = types.SimpleNamespace(image_generator_id=gen_id)
        fake_generator = object()

        with patch(
            "giga_agent.generators.image.tool.ImageGeneratorManager.resolve_by_id",
            AsyncMock(return_value=fake_generator),
        ) as mocked_resolve:
            resolved = await _resolve_generator_for_user(user)

        mocked_resolve.assert_awaited_once_with(gen_id)
        self.assertIs(resolved, fake_generator)

    async def test_resolve_generator_raises_when_id_not_selected(self):
        user = types.SimpleNamespace(image_generator_id=None)

        with self.assertRaisesRegex(ValueError, "не выбран генератор"):
            await _resolve_generator_for_user(user)

    async def test_resolve_generator_does_not_open_session_factory(self):
        gen_id = uuid.uuid4()
        user = types.SimpleNamespace(image_generator_id=gen_id)

        with patch(
            "giga_agent.generators.image.tool.get_session_factory",
            AsyncMock(side_effect=AssertionError("must not be called")),
        ), patch(
            "giga_agent.generators.image.tool.ImageGeneratorManager.resolve_by_id",
            AsyncMock(return_value=object()),
        ):
            await _resolve_generator_for_user(user)
