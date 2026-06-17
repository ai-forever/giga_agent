"""Discovery of built-in skills shipped with giga_agent."""

from __future__ import annotations

from pathlib import Path

from giga_agent.modules.skills.manifest import find_skill_manifest_path
from giga_agent.modules.skills.parser import SkillParseError, parse_skill_md

_SKILLS_PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


def get_builtin_skills_dir() -> Path:
    return _SKILLS_PACKAGE_DIR


def get_builtin_skill_dir(name: str) -> Path | None:
    candidate = _SKILLS_PACKAGE_DIR / name
    if candidate.is_dir() and find_skill_manifest_path(candidate) is not None:
        return candidate
    return None


def list_builtin_skills() -> list[dict]:
    """Return metadata for all built-in skills."""
    result: list[dict] = []
    if not _SKILLS_PACKAGE_DIR.is_dir():
        return result
    for entry in sorted(_SKILLS_PACKAGE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = find_skill_manifest_path(entry)
        if skill_md is None:
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
            parsed = parse_skill_md(content)
            result.append(
                {
                    "name": parsed.name,
                    "description": parsed.description,
                }
            )
        except (SkillParseError, OSError):
            continue
    return result
