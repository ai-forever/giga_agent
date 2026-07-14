import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from giga_agent.cli.utils.secret_key import ensure_dev_secret_key_env


class DevSecretKeyEnvTests(unittest.TestCase):
    def test_does_not_change_when_env_is_set(self):
        with tempfile.TemporaryDirectory() as td:
            secret_file = Path(td) / ".secret_key"
            secret_file.write_text("file-secret\n", encoding="utf-8")

            with patch.dict(
                os.environ, {"GIGA_AGENT_SECRET_KEY": "env-secret"}, clear=True
            ):
                ensure_dev_secret_key_env()

            self.assertEqual(secret_file.read_text(encoding="utf-8"), "file-secret\n")

    def test_reads_secret_from_file_when_env_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".secret_key").write_text("file-secret\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True), patch(
                "giga_agent.core.paths.ensure_giga_agent_dir",
                return_value=root,
            ):
                ensure_dev_secret_key_env()
                self.assertEqual(os.environ["GIGA_AGENT_SECRET_KEY"], "file-secret")

    def test_generates_secret_when_file_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            secret_file = root / ".secret_key"

            with patch.dict(os.environ, {}, clear=True), patch(
                "giga_agent.core.paths.ensure_giga_agent_dir",
                return_value=root,
            ):
                ensure_dev_secret_key_env()
                generated = os.environ["GIGA_AGENT_SECRET_KEY"]
                self.assertTrue(secret_file.exists())
                self.assertEqual(
                    secret_file.read_text(encoding="utf-8"), f"{generated}\n"
                )
                self.assertEqual(len(generated), 64)

    def test_regenerates_secret_when_file_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            secret_file = root / ".secret_key"
            secret_file.write_text("\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True), patch(
                "giga_agent.core.paths.ensure_giga_agent_dir",
                return_value=root,
            ):
                ensure_dev_secret_key_env()
                generated = os.environ["GIGA_AGENT_SECRET_KEY"]
                self.assertEqual(
                    secret_file.read_text(encoding="utf-8"), f"{generated}\n"
                )
                self.assertEqual(len(generated), 64)
