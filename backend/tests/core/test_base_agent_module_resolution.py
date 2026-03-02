import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule


class _DummyModule(BaseModule):
    id: str


class _AgentWithDefaults(BaseAgent):
    def get_modules(self) -> list[BaseModule]:
        return [_DummyModule(id="default_one"), _DummyModule(id="default_two")]


class BaseAgentModuleResolutionTests(unittest.TestCase):
    @contextmanager
    def _secret_key_env(self):
        with patch.dict(os.environ, {"GIGA_AGENT_SECRET_KEY": "test-secret"}, clear=False):
            yield

    def test_merges_get_modules_before_explicit_modules(self):
        with self._secret_key_env():
            agent = _AgentWithDefaults(modules=(_DummyModule(id="extra"),))

        self.assertEqual(
            [module.id for module in agent.all_modules],
            ["default_one", "default_two", "extra"],
        )

    def test_raises_on_duplicate_id_between_get_modules_and_modules(self):
        with self._secret_key_env():
            with self.assertRaises(ValueError):
                _AgentWithDefaults(modules=(_DummyModule(id="default_one"),))
