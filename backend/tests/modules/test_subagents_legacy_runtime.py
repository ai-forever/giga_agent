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

    async def test_capabilities_snapshot(self):
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
        caps = await get_legacy_capabilities(user)
        self.assertTrue(caps.has_llm)
        self.assertTrue(caps.has_search)
        self.assertTrue(caps.has_image_generator)
        self.assertTrue(caps.has_twogis_token)
        self.assertTrue(caps.has_salute_speech)
        self.assertTrue(caps.has_salute_scope)

    async def test_resolvers_use_runtime_resolver(self):
        # With a config the resolvers delegate to the RuntimeResolver injected in
        # (or created from) that config — not to the per-manager resolve_by_id.
        user = types.SimpleNamespace(
            llm_id=uuid.uuid4(),
            search_engine_id=uuid.uuid4(),
            image_generator_id=uuid.uuid4(),
            secrets={},
        )
        config = {"configurable": {}}
        llm_runtime = types.SimpleNamespace(get_llm=AsyncMock(return_value="llm"))
        resolver = types.SimpleNamespace(
            get_llm_runtime=AsyncMock(return_value=llm_runtime),
            get_search_engine=AsyncMock(return_value="search"),
            get_image_generator=AsyncMock(return_value="image"),
        )

        with patch(
            "giga_agent.modules.subagents_legacy.runtime.RuntimeResolver.from_config",
            return_value=resolver,
        ):
            self.assertEqual(await resolve_user_llm(user, config=config), "llm")
            self.assertEqual(
                await resolve_user_search_engine(user, config=config),
                "search",
            )
            self.assertEqual(
                await resolve_user_image_generator(user, config=config),
                "image",
            )

        resolver.get_llm_runtime.assert_awaited_once_with()
        resolver.get_search_engine.assert_awaited_once_with()
        resolver.get_image_generator.assert_awaited_once_with()
