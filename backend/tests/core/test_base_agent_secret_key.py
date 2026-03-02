import os
import unittest
from unittest.mock import patch

from giga_agent.core.agent.base import BaseAgent


class BaseAgentSecretKeyRequirementTests(unittest.TestCase):
    def test_raises_when_secret_key_env_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception) as exc:
                BaseAgent(modules=[], tools=[])

        self.assertEqual(
            str(exc.exception),
            "GIGA_AGENT_SECRET_KEY is not set. Please set env secret key.",
        )
