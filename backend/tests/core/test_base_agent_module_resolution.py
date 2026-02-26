import unittest

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule


class _DummyModule(BaseModule):
    id: str


class _AgentWithDefaults(BaseAgent):
    def get_modules(self) -> list[BaseModule]:
        return [_DummyModule(id="default_one"), _DummyModule(id="default_two")]


class BaseAgentModuleResolutionTests(unittest.TestCase):
    def test_merges_get_modules_before_explicit_modules(self):
        agent = _AgentWithDefaults(modules=(_DummyModule(id="extra"),))

        self.assertEqual(
            [module.id for module in agent.modules],
            ["default_one", "default_two", "extra"],
        )

    def test_raises_on_duplicate_id_between_get_modules_and_modules(self):
        with self.assertRaises(ValueError):
            _AgentWithDefaults(modules=(_DummyModule(id="default_one"),))
