from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx
import typer

from giga_agent.cli.utils.imports import load_agent_from_string
from giga_agent.modules.skills.parser import parse_skill_md
from giga_agent.modules.skills.service import SkillInstallError, SkillsService

agents_app = typer.Typer(help="List, validate, and install built-in subagents.")


def _load(agent_path: str):
    return load_agent_from_string(agent_path)


def _find(agent, agent_id: str):
    matches = [
        item
        for item in agent.subagent_registry.builtins
        if item.ref == agent_id or item.id == agent_id
    ]
    if len(matches) != 1:
        raise typer.BadParameter(f"Unknown or ambiguous built-in agent: {agent_id}")
    return matches[0]


@agents_app.command("list")
def list_agents(
    agent_path: str = typer.Option(
        "giga_agent.agents.run:agent", "--agent-path", help="Agent import path"
    ),
) -> None:
    agent = _load(agent_path)
    for item in agent.subagent_registry.builtins:
        typer.echo(f"{item.ref}\t{item.name}\t{item.description}")


@agents_app.command("check")
def check_agent(
    agent_id: str,
    agent_path: str = typer.Option("giga_agent.agents.run:agent", "--agent-path"),
) -> None:
    agent = _load(agent_path)
    definition = _find(agent, agent_id)
    module_ids = {module.id for module in agent.all_modules}
    unknown = sorted(set(definition.modules) - module_ids)
    if unknown:
        typer.echo(f"Unknown modules: {', '.join(unknown)}", err=True)
        raise typer.Exit(code=1)
    skills_root = Path.cwd() / ".agents" / "skills"
    missing_skills = [
        item.name
        for item in definition.skills
        if not (skills_root / item.name / "SKILL.md").is_file()
    ]
    if missing_skills:
        typer.echo(f"needs_setup: missing skills: {', '.join(missing_skills)}")
        raise typer.Exit(code=1)
    if definition.connectors:
        typer.echo(
            "needs_setup: connector bindings are checked when the CLI graph starts: "
            + ", ".join(definition.connectors)
        )
        raise typer.Exit(code=1)
    typer.echo(f"ready: {definition.ref}")


def _install_archive_skill(source: str, ref: str, name: str, destination: Path) -> None:
    url = f"https://github.com/{source}/archive/{quote(ref, safe='')}.zip"
    response = httpx.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    if len(response.content) > 20 * 1024 * 1024:
        raise SkillInstallError("GitHub archive exceeds 20 MiB")
    with tempfile.TemporaryDirectory(prefix="giga_agent_cli_skill_") as temp:
        extracted = Path(temp) / "archive"
        extracted.mkdir()
        SkillsService._extract_archive(response.content, "skill.zip", extracted)
        matches: list[Path] = []
        for manifest in extracted.rglob("SKILL.md"):
            parsed = parse_skill_md(manifest.read_text(encoding="utf-8"))
            if parsed.name == name:
                matches.append(manifest.parent)
        if len(matches) != 1:
            raise SkillInstallError(
                f"Expected one SKILL.md for {name!r}, found {len(matches)}"
            )
        if destination.exists():
            metadata_path = destination / ".giga-agent-source.json"
            existing = (
                json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
            )
            if existing.get("source") != source or existing.get("ref") != ref:
                raise SkillInstallError(
                    f"Skill {name!r} already exists from another source/ref"
                )
            typer.echo(f"already installed: {name}")
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.installing-", dir=destination.parent
            )
        )
        staging = staging_root / "payload"
        shutil.copytree(matches[0], staging)
        (staging / ".giga-agent-source.json").write_text(
            json.dumps({"source": source, "ref": ref}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging.rename(destination)
        staging_root.rmdir()


@agents_app.command("install")
def install_agent(
    agent_id: str,
    agent_path: str = typer.Option("giga_agent.agents.run:agent", "--agent-path"),
) -> None:
    agent = _load(agent_path)
    definition = _find(agent, agent_id)
    if not definition.skills:
        typer.echo(f"no skills to install for {definition.ref}")
        return
    root = Path.cwd() / ".agents" / "skills"
    for requirement in definition.skills:
        if not requirement.source:
            raise typer.BadParameter(
                f"Skill {requirement.name!r} has no GitHub source and cannot be installed automatically"
            )
        try:
            _install_archive_skill(
                requirement.source,
                requirement.ref or "HEAD",
                requirement.name,
                root / requirement.name,
            )
        except (httpx.HTTPError, SkillInstallError, ValueError) as exc:
            typer.echo(f"failed to install {requirement.name}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"installed: {requirement.name}")
