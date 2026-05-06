"""SKILL.md parser — YAML frontmatter + markdown body."""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_BODY_CHARS = 20_000


class SkillParseError(ValueError):
    """Raised when SKILL.md cannot be parsed or fails validation."""


@dataclass(frozen=True, slots=True)
class ParsedSkill:
    name: str
    description: str
    body: str
    metadata: dict


def parse_skill_md(content: str) -> ParsedSkill:
    """
    Parse a SKILL.md file with YAML frontmatter delimited by ``---``.

    Expected format::

        ---
        name: my-skill
        description: Short description of the skill
        ...optional fields...
        ---

        Markdown body with full instructions...
    """
    content = content.strip()
    if not content.startswith("---"):
        raise SkillParseError("SKILL.md must start with '---' (YAML frontmatter)")

    # Find the closing --- delimiter (skip the opening one)
    second_delim = content.find("---", 3)
    if second_delim == -1:
        raise SkillParseError("SKILL.md missing closing '---' for YAML frontmatter")

    frontmatter_raw = content[3:second_delim].strip()
    body = content[second_delim + 3 :].strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"Invalid YAML frontmatter: {e}") from e

    if not isinstance(frontmatter, dict):
        raise SkillParseError("YAML frontmatter must be a mapping")

    name = frontmatter.get("name")
    if not name or not isinstance(name, str):
        raise SkillParseError("SKILL.md frontmatter must contain a 'name' string field")

    name = name.strip().lower()
    if len(name) > MAX_NAME_LEN:
        raise SkillParseError(f"Skill name exceeds {MAX_NAME_LEN} characters")
    if not SKILL_NAME_RE.match(name):
        raise SkillParseError(
            f"Skill name '{name}' is invalid. "
            f"Must match pattern: ^[a-z][a-z0-9-]*[a-z0-9]$ "
            f"(lowercase letters, digits, hyphens; start with letter, end with letter/digit)"
        )

    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        description = str(description)
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LEN:
        description = description[:MAX_DESCRIPTION_LEN]

    if len(body) > MAX_BODY_CHARS:
        raise SkillParseError(
            f"SKILL.md body exceeds {MAX_BODY_CHARS} characters ({len(body)})"
        )

    metadata = {
        k: v for k, v in frontmatter.items() if k not in ("name", "description")
    }

    return ParsedSkill(
        name=name,
        description=description,
        body=body,
        metadata=metadata,
    )
