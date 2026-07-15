import unittest

from giga_agent.core.module import collect_module_secrets
from giga_agent.modules.integrations.vk import VKModule
from giga_agent.modules.weather import WeatherModule


class ServiceModulesSecretsTests(unittest.TestCase):
    def test_collect_module_secrets_contains_all_new_keys_without_duplicates(self):
        secrets = collect_module_secrets([VKModule(), WeatherModule(), VKModule()])
        names = [item["name"] for item in secrets]
        self.assertEqual(
            names,
            ["VK_TOKEN", "OWM_API_KEY"],
        )
