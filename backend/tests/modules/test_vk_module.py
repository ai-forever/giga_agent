import types
import unittest

from giga_agent.modules.vk import VKModule


class VKModuleTests(unittest.IsolatedAsyncioTestCase):
    def test_get_secrets_contract(self):
        module = VKModule()
        self.assertEqual(
            module.get_secrets(),
            [
                {
                    "name": "VK_TOKEN",
                    "description": "Токен VK API для чтения постов и комментариев.",
                    "type": "pass",
                }
            ],
        )

    async def test_get_tools_hidden_without_secret(self):
        module = VKModule()
        user = types.SimpleNamespace(secrets={})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(tools, [])

    async def test_get_tools_available_with_secret(self):
        module = VKModule()
        user = types.SimpleNamespace(secrets={"VK_TOKEN": "token"})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(
            sorted(tool.name for tool in tools),
            sorted(["vk_get_posts", "vk_get_comments", "vk_get_last_comments"]),
        )
