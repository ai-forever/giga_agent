import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.modules.subagents_legacy.runtime import (
    get_legacy_capabilities,
    get_user_secret,
    resolve_user_image_generator,
    resolve_user_llm,
    resolve_user_search_engine,
)


class SubagentsLegacyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_get_user_secret_uses_uppercase_only(self):
        user = types.SimpleNamespace(
            secrets={
                "TWOGIS_TOKEN": "abc",
                "two_gis_token": "ignored",
            }
        )
        self.assertEqual(get_user_secret(user, "TWOGIS_TOKEN"), "abc")
        self.assertIsNone(get_user_secret(user, "SALUTE_SPEECH"))

    def test_capabilities_snapshot(self):
        user = types.SimpleNamespace(
            llm_id=uuid.uuid4(),
            search_engine_id=uuid.uuid4(),
            image_generator_id=uuid.uuid4(),
            secrets={
                "TWOGIS_TOKEN": "twogis",
                "SALUTE_SPEECH": "speech",
                "SALUTE_SCOPE": "scope",
            },
        )
        caps = get_legacy_capabilities(user)
        self.assertTrue(caps.has_llm)
        self.assertTrue(caps.has_search)
        self.assertTrue(caps.has_image_generator)
        self.assertTrue(caps.has_twogis_token)
        self.assertTrue(caps.has_salute_speech)
        self.assertTrue(caps.has_salute_scope)

    async def test_resolvers_use_managers(self):
        user = types.SimpleNamespace(
            llm_id=uuid.uuid4(),
            search_engine_id=uuid.uuid4(),
            image_generator_id=uuid.uuid4(),
        )
        with patch(
            "giga_agent.modules.subagents_legacy.runtime.LLMManager.resolve_by_id",
            AsyncMock(return_value="llm"),
        ) as llm_resolve, patch(
            "giga_agent.modules.subagents_legacy.runtime.SearchEngineManager.resolve_by_id",
            AsyncMock(return_value="search"),
        ) as search_resolve, patch(
            "giga_agent.modules.subagents_legacy.runtime.ImageGeneratorManager.resolve_by_id",
            AsyncMock(return_value="image"),
        ) as image_resolve:
            self.assertEqual(await resolve_user_llm(user), "llm")
            self.assertEqual(await resolve_user_search_engine(user), "search")
            self.assertEqual(await resolve_user_image_generator(user), "image")

        llm_resolve.assert_awaited_once_with(user.llm_id)
        search_resolve.assert_awaited_once_with(user.search_engine_id)
        image_resolve.assert_awaited_once_with(user.image_generator_id)
