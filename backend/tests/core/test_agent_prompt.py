from pathlib import Path
from unittest.mock import patch

import pytest

from giga_agent.conf import reset_settings_cache
from giga_agent.core.agent.prompt import build_base_prompt


@pytest.mark.anyio
async def test_build_base_prompt_includes_cli_agents_md(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("Use project-specific rules.", encoding="utf-8")

    with patch.dict(
        "os.environ",
        {
            "GIGA_AGENT_RUNTIME": "cli",
            "GIGA_AGENT_CLI_CWD": str(tmp_path),
        },
    ):
        reset_settings_cache()
        prompt = await build_base_prompt()
    reset_settings_cache()

    assert "AGENTS.md" in prompt
    assert "Use project-specific rules." in prompt


@pytest.mark.anyio
async def test_build_base_prompt_includes_cli_agents_md_uppercase(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.MD"
    agents_md.write_text("Use uppercase project rules.", encoding="utf-8")

    with patch.dict(
        "os.environ",
        {
            "GIGA_AGENT_RUNTIME": "cli",
            "GIGA_AGENT_CLI_CWD": str(tmp_path),
        },
    ):
        reset_settings_cache()
        prompt = await build_base_prompt()
    reset_settings_cache()

    assert "AGENTS.md" in prompt
    assert "Use uppercase project rules." in prompt


@pytest.mark.anyio
async def test_build_base_prompt_escapes_cli_agents_md_format_literals(
    tmp_path: Path,
):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        'Example config: {"model": "gpt-4o", "temperature": 0}.',
        encoding="utf-8",
    )

    with patch.dict(
        "os.environ",
        {
            "GIGA_AGENT_RUNTIME": "cli",
            "GIGA_AGENT_CLI_CWD": str(tmp_path),
        },
    ):
        reset_settings_cache()
        prompt = await build_base_prompt()
    reset_settings_cache()

    formatted_prompt = prompt.format(modules="Module instructions.")

    assert 'Example config: {"model": "gpt-4o", "temperature": 0}.' in formatted_prompt
    assert "Module instructions." in formatted_prompt


@pytest.mark.anyio
async def test_build_base_prompt_skips_agents_md_outside_cli(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("Use project-specific rules.", encoding="utf-8")

    with patch.dict(
        "os.environ",
        {
            "GIGA_AGENT_RUNTIME": "local",
            "GIGA_AGENT_CLI_CWD": str(tmp_path),
        },
    ):
        reset_settings_cache()
        prompt = await build_base_prompt()
    reset_settings_cache()

    assert "Use project-specific rules." not in prompt
