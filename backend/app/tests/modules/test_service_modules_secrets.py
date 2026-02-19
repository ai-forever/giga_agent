import unittest

from giga_agent.core.module import collect_module_secrets
from giga_agent.modules.github import GitHubModule
from giga_agent.modules.vk import VKModule
from giga_agent.modules.weather import WeatherModule


class ServiceModulesSecretsTests(unittest.TestCase):
    def test_collect_module_secrets_contains_all_new_keys_without_duplicates(self):
        secrets = collect_module_secrets(
            [GitHubModule(), VKModule(), WeatherModule(), GitHubModule()]
        )
        names = [item["name"] for item in secrets]
        self.assertEqual(
            names,
            ["GITHUB_PERSONAL_ACCESS_TOKEN", "VK_TOKEN", "OWM_API_KEY"],
        )
