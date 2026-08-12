"""Tests for CLI runtime configuration loading and CliRuntimeResolver."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from giga_agent.core.agent.cli_conf import (
    CliRuntimeConf,
    CliConnectorConf,
    CliLLMConf,
    CliEmbeddingConf,
    load_cli_conf,
    reset_cli_conf_cache,
    CONF_FILENAME,
)


SAMPLE_CONF = {
    "llm": {
        "connector": {"__type": "openai", "api_key": "sk-test-123"},
        "__type": "openai",
        "model_id": "gpt-4o",
    },
    "fast_llm": {
        "connector": {"__type": "openai", "api_key": "sk-test-123"},
        "__type": "openai",
        "model_id": "gpt-4o-mini",
    },
    "embedding": {
        "connector": {"__type": "openai", "api_key": "sk-test-123"},
        "__type": "openai_embedding",
        "model_id": "text-embedding-3-small",
        "vector_size": 1536,
    },
    "sandbox": "local_jupyter",
    "search_engine": {
        "connector": {"__type": "tavily", "api_key": "tvly-test"},
        "__type": "tavily",
    },
    "image_generator": None,
    "user_settings": {"contextInstructions": "Be helpful"},
}


class TestCliConnectorConf:
    def test_type_from_alias(self):
        conf = CliConnectorConf.model_validate(
            {"__type": "openai", "api_key": "sk-123", "organization": "org-abc"}
        )
        assert conf.type == "openai"
        assert conf.settings == {"api_key": "sk-123", "organization": "org-abc"}

    def test_empty_settings(self):
        conf = CliConnectorConf.model_validate({"__type": "tavily"})
        assert conf.type == "tavily"
        assert conf.settings == {}


class TestCliLLMConf:
    def test_parse(self):
        conf = CliLLMConf.model_validate(
            {
                "connector": {"__type": "openai", "api_key": "sk-x"},
                "__type": "openai",
                "model_id": "gpt-4o",
                "temperature": 0.7,
            }
        )
        assert conf.type == "openai"
        assert conf.model_id == "gpt-4o"
        assert conf.connector.type == "openai"
        assert conf.connector.settings == {"api_key": "sk-x"}
        assert conf.settings == {"temperature": 0.7}


class TestCliEmbeddingConf:
    def test_default_vector_size(self):
        conf = CliEmbeddingConf.model_validate(
            {
                "connector": {"__type": "openai", "api_key": "sk-x"},
                "__type": "openai_embedding",
                "model_id": "text-embedding-3-small",
            }
        )
        assert conf.vector_size == 1536

    def test_custom_vector_size(self):
        conf = CliEmbeddingConf.model_validate(
            {
                "connector": {"__type": "openai", "api_key": "sk-x"},
                "__type": "openai_embedding",
                "model_id": "text-embedding-3-large",
                "vector_size": 3072,
            }
        )
        assert conf.vector_size == 3072


class TestCliRuntimeConf:
    def test_full_parse(self):
        conf = CliRuntimeConf.model_validate(SAMPLE_CONF)
        assert conf.llm.type == "openai"
        assert conf.llm.model_id == "gpt-4o"
        assert conf.fast_llm is not None
        assert conf.fast_llm.model_id == "gpt-4o-mini"
        assert conf.embedding is not None
        assert conf.embedding.type == "openai_embedding"
        assert conf.sandbox == "local_jupyter"
        assert conf.search_engine is not None
        assert conf.search_engine.type == "tavily"
        assert conf.image_generator is None
        assert conf.user_settings == {"contextInstructions": "Be helpful"}

    def test_minimal(self):
        minimal = {
            "llm": {
                "connector": {"__type": "openai", "api_key": "sk-x"},
                "__type": "openai",
                "model_id": "gpt-4o",
            }
        }
        conf = CliRuntimeConf.model_validate(minimal)
        assert conf.llm.type == "openai"
        assert conf.fast_llm is None
        assert conf.embedding is None
        assert conf.sandbox == "local_jupyter"


class TestLoadCliConf:
    def test_load_from_cwd(self, tmp_path, monkeypatch):
        reset_cli_conf_cache()
        conf_file = tmp_path / CONF_FILENAME
        conf_file.write_text(json.dumps(SAMPLE_CONF))
        monkeypatch.chdir(tmp_path)
        conf = load_cli_conf()
        assert conf.llm.type == "openai"
        reset_cli_conf_cache()

    def test_load_from_giga_agent_dir(self, tmp_path, monkeypatch):
        reset_cli_conf_cache()
        giga_dir = tmp_path / ".giga_agent"
        giga_dir.mkdir()
        conf_file = giga_dir / CONF_FILENAME
        conf_file.write_text(json.dumps(SAMPLE_CONF))
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        with patch(
            "giga_agent.core.paths.giga_agent_dir",
            return_value=giga_dir,
        ):
            conf = load_cli_conf()
        assert conf.llm.model_id == "gpt-4o"
        reset_cli_conf_cache()

    def test_file_not_found(self, tmp_path, monkeypatch):
        reset_cli_conf_cache()
        monkeypatch.chdir(tmp_path)
        with patch(
            "giga_agent.core.paths.giga_agent_dir",
            return_value=tmp_path / "nonexistent",
        ):
            with pytest.raises(FileNotFoundError):
                load_cli_conf()
        reset_cli_conf_cache()


class TestCliRuntimeResolver(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_cli_conf_cache()

    def tearDown(self):
        reset_cli_conf_cache()

    def _write_conf(self, tmp_dir: Path, data: dict) -> None:
        conf_file = tmp_dir / CONF_FILENAME
        conf_file.write_text(json.dumps(data))

    async def test_create_synthetic_user(self, tmp_path=None):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_conf(tmp_path, SAMPLE_CONF)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                resolver = await CliRuntimeResolver.create({})
                self.assertTrue(resolver.user.is_synthetic)
                self.assertEqual(resolver.user.email, "cli@giga-agent.local.dev")
                self.assertTrue(resolver.user.is_superuser)
                self.assertEqual(
                    resolver.user.settings, {"contextInstructions": "Be helpful"}
                )
            finally:
                os.chdir(orig_cwd)

    async def test_has_properties(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_conf(tmp_path, SAMPLE_CONF)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                resolver = await CliRuntimeResolver.create({})
                self.assertTrue(resolver.has_llm)
                self.assertTrue(resolver.has_fast_llm)
                self.assertTrue(resolver.has_embedding)
                self.assertTrue(resolver.has_sandbox)
                self.assertTrue(resolver.has_search_engine)
                self.assertFalse(resolver.has_image_generator)
            finally:
                os.chdir(orig_cwd)

    async def test_has_properties_minimal(self):
        import tempfile

        minimal = {
            "llm": {
                "connector": {"__type": "openai", "api_key": "sk-x"},
                "__type": "openai",
                "model_id": "gpt-4o",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_conf(tmp_path, minimal)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                resolver = await CliRuntimeResolver.create({})
                self.assertTrue(resolver.has_llm)
                self.assertTrue(resolver.has_fast_llm)  # falls back to llm
                self.assertFalse(resolver.has_embedding)
                self.assertFalse(resolver.has_search_engine)
                self.assertFalse(resolver.has_image_generator)
            finally:
                os.chdir(orig_cwd)

    async def test_get_sandbox_returns_local_jupyter(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_conf(tmp_path, SAMPLE_CONF)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                resolver = await CliRuntimeResolver.create({})
                resolved = await resolver.get_sandbox()
                self.assertEqual(resolved.provider.type, "local_jupyter")
                self.assertEqual(resolved.sandbox.status, "pending")
                self.assertEqual(
                    resolved.provider.settings["python_executor"], "worker"
                )
            finally:
                os.chdir(orig_cwd)

    async def test_get_sandbox_includes_cli_cwd_runtime_settings(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cwd_path = tmp_path / "work"
            cwd_path.mkdir()
            self._write_conf(tmp_path, SAMPLE_CONF)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.conf import reset_settings_cache
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                with patch.dict(os.environ, {"GIGA_AGENT_CLI_CWD": str(cwd_path)}):
                    reset_settings_cache()
                    resolver = await CliRuntimeResolver.create({})
                    resolved = await resolver.get_sandbox()
                reset_settings_cache()

                self.assertEqual(
                    resolved.provider.settings["default_cwd"],
                    str(cwd_path.resolve()),
                )
                self.assertEqual(
                    resolved.provider.settings["write_dirs"],
                    [str(cwd_path.resolve())],
                )
            finally:
                os.chdir(orig_cwd)

    async def test_get_sandbox_uses_worker_executor_from_cli_environment(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_conf(tmp_path, SAMPLE_CONF)
            orig_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                from giga_agent.conf import reset_settings_cache
                from giga_agent.core.agent.runtime_resolver import CliRuntimeResolver

                with patch.dict(
                    os.environ,
                    {"GIGA_AGENT_CLI_PYTHON_EXECUTOR": "worker"},
                ):
                    reset_settings_cache()
                    resolver = await CliRuntimeResolver.create({})
                    resolved = await resolver.get_sandbox()
                reset_settings_cache()

                self.assertEqual(
                    resolved.provider.settings["python_executor"], "worker"
                )
            finally:
                os.chdir(orig_cwd)
