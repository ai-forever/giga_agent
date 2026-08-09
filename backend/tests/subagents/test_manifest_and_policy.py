from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.tools import tool

from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.module import BaseModule
from giga_agent.modules.skills.service import SkillInstallError, SkillsService
from giga_agent.subagents.execution import AgentExecutionProfile, direct_tool_allowed
from giga_agent.subagents.parser import AgentManifestError, parse_agent_manifest
from giga_agent.subagents.registry import AgentRegistry
from giga_agent.subagents.schema import AgentToolRules


def _manifest(agent_id: str = "researcher", *, extra: str = "") -> str:
    return f"""---
schema_version: 1
id: {agent_id}
name: Researcher
description: Researches a topic.
modules: [search]
tools:
  default: read
  allow: [io/write_file]
  deny: [io/read_secret]
{extra}---

Do the research and return a sourced report.
"""


def test_parse_agent_manifest_contract(tmp_path: Path) -> None:
    path = tmp_path / "AGENT.md"
    path.write_text(_manifest(), encoding="utf-8")

    parsed = parse_agent_manifest(path)

    assert parsed.metadata.id == "researcher"
    assert parsed.metadata.tools.default == "read"
    assert parsed.prompt.startswith("Do the research")


@pytest.mark.parametrize(
    "content",
    [
        "no frontmatter",
        "---\nid: broken\n---\nbody",
        _manifest(extra="owner: forbidden\n"),
        _manifest(extra="limits: {}\n"),
        _manifest(extra="enabled: true\n"),
        _manifest(extra="graph: other\n"),
        _manifest(extra="unknown: true\n"),
        _manifest().replace("Do the research and return a sourced report.", ""),
    ],
)
def test_parse_agent_manifest_rejects_invalid_contract(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "AGENT.md"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(AgentManifestError):
        parse_agent_manifest(path)


class _ManifestModule(BaseModule):
    id: str
    manifests: list[str]

    def get_agents(self, **kwargs):
        return self.manifests


def test_registry_rejects_duplicate_plain_ids(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text(_manifest(), encoding="utf-8")
    second.write_text(_manifest(), encoding="utf-8")
    agent = SimpleNamespace(
        all_modules=(
            _ManifestModule(id="one", manifests=[str(first)]),
            _ManifestModule(id="two", manifests=[str(second)]),
        )
    )
    with pytest.raises(ValueError, match="duplicate built-in agent id"):
        AgentRegistry(agent)


def test_direct_tool_policy_is_fail_closed_and_deny_wins() -> None:
    @tool(extras=tool_extras(ToolEffect.READ))
    def read_file() -> str:
        """Read a file."""
        return "ok"

    @tool(extras=tool_extras(ToolEffect.WRITE))
    def write_file() -> str:
        """Write a file."""
        return "ok"

    @tool
    def unknown() -> str:
        """Tool without trusted effect."""
        return "no"

    definition = SimpleNamespace(
        tools=AgentToolRules(allow=["io/write_file"], deny=["io/read_file"])
    )
    profile = AgentExecutionProfile(definition, frozenset(), frozenset())
    assert not direct_tool_allowed(profile, "io", read_file)
    assert direct_tool_allowed(profile, "io", write_file)
    assert not direct_tool_allowed(profile, "io", unknown)
    assert not direct_tool_allowed(profile, "io", write_file, parent_plan_mode=True)


def test_custom_tool_effects_allow_selected_categories_only() -> None:
    @tool(extras=tool_extras(ToolEffect.READ))
    def read_file() -> str:
        """Read a file."""
        return "ok"

    @tool(extras=tool_extras(ToolEffect.WRITE))
    def write_file() -> str:
        """Write a file."""
        return "ok"

    @tool(extras=tool_extras(ToolEffect.DESTRUCTIVE))
    def delete_file() -> str:
        """Delete a file."""
        return "ok"

    definition = SimpleNamespace(
        source="custom",
        tools=AgentToolRules(),
    )
    read_only = AgentExecutionProfile(
        definition,
        frozenset(),
        frozenset(),
        frozenset({"read"}),
    )
    assert direct_tool_allowed(read_only, "io", read_file)
    assert not direct_tool_allowed(read_only, "io", write_file)
    assert not direct_tool_allowed(read_only, "io", delete_file)

    with_write = AgentExecutionProfile(
        definition,
        frozenset(),
        frozenset(),
        frozenset({"read", "write"}),
    )
    assert direct_tool_allowed(with_write, "io", write_file)
    assert not direct_tool_allowed(with_write, "io", delete_file)
    assert direct_tool_allowed(with_write, "io", read_file, parent_plan_mode=True)
    assert not direct_tool_allowed(with_write, "io", write_file, parent_plan_mode=True)


def test_skill_archive_rejects_zip_traversal(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escaped.txt", "unsafe")

    with pytest.raises(SkillInstallError, match="Unsafe archive path"):
        SkillsService._extract_archive(archive.getvalue(), "skill.zip", tmp_path)
