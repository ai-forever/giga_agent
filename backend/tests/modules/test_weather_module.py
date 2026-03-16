import types
import unittest

from giga_agent.modules.weather import WeatherModule


class WeatherModuleTests(unittest.IsolatedAsyncioTestCase):
    def test_get_secrets_contract(self):
        module = WeatherModule()
        self.assertEqual(
            module.get_secrets(),
            [
                {
                    "name": "OWM_API_KEY",
                    "description": "API key OpenWeatherMap для текущей и прогнозной погоды.",
                    "type": "pass",
                }
            ],
        )

    async def test_get_tools_hidden_without_secret(self):
        module = WeatherModule()
        user = types.SimpleNamespace(secrets={})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(tools, [])

    async def test_get_tools_available_with_secret(self):
        module = WeatherModule()
        user = types.SimpleNamespace(secrets={"OWM_API_KEY": "token"})
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual([tool.name for tool in tools], ["weather"])
