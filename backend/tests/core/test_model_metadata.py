import pytest
from pydantic import ValidationError

from giga_agent.conf import Settings
from giga_agent.core.agent.cli_conf import CliRuntimeConf
from giga_agent.model_metadata import DEFAULT_CONTEXT_WINDOW, resolve_context_window


def test_context_window_resolution_precedence() -> None:
    assert resolve_context_window("GigaChat-2", 42_000) == 42_000
    assert resolve_context_window("GigaChat-2") == 128_000
    assert resolve_context_window("unknown-model") == DEFAULT_CONTEXT_WINDOW


def test_compaction_ratio_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(
            GIGA_AGENT_CONTEXT_COMPACTION_TRIGGER_RATIO=0.9,
            GIGA_AGENT_CONTEXT_COMPACTION_HARD_RATIO=0.8,
        )


def test_cli_context_window_must_be_positive() -> None:
    data = {
        "llm": {
            "connector": {"__type": "openai"},
            "__type": "openai",
            "model_id": "model",
            "context_window": 0,
        }
    }
    with pytest.raises(ValidationError):
        CliRuntimeConf.model_validate(data)
