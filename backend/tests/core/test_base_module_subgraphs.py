import unittest

from giga_agent.core.module import BaseModule


class _DummyModule(BaseModule):
    id: str = "dummy"


class BaseModuleSubgraphsTests(unittest.TestCase):
    def test_default_get_subgraphs_is_empty_dict(self):
        module = _DummyModule()
        self.assertEqual(module.get_subgraphs(), {})
