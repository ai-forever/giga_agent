from __future__ import annotations

import re
from dataclasses import dataclass

import yaml


_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\n(?P<header>.*?)\n---[ \t]*(?:\n|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True)
class FrontmatterParseResult:
    description: str | None
    body: str
    valid: bool
    had_block: bool


def _description_from_data(data) -> str | None:
    if not isinstance(data, dict):
        return None
    desc = data.get("description")
    if not isinstance(desc, str):
        return None
    trimmed = desc.strip()
    if not trimmed:
        return None
    return trimmed[:512]


def parse_frontmatter(content: str) -> FrontmatterParseResult:
    """Parse YAML frontmatter at the start of *content*.

    Returns description (если есть), body без frontmatter и флаги. Толерантен
    к битому YAML — возвращает ``valid=False`` без исключения.
    """
    if not content:
        return FrontmatterParseResult(
            description=None, body=content, valid=True, had_block=False
        )

    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return FrontmatterParseResult(
            description=None, body=content, valid=True, had_block=False
        )

    header = match.group("header")
    body = content[match.end() :]

    try:
        data = yaml.safe_load(header)
    except yaml.YAMLError:
        return FrontmatterParseResult(
            description=None, body=body, valid=False, had_block=True
        )

    description = _description_from_data(data)
    if data is not None and not isinstance(data, dict):
        # Not a mapping — treat as malformed.
        return FrontmatterParseResult(
            description=None, body=body, valid=False, had_block=True
        )

    return FrontmatterParseResult(
        description=description,
        body=body,
        valid=True,
        had_block=True,
    )


def serialize_frontmatter(description: str, body: str) -> str:
    """Build content with a fresh, single-key ``description:`` frontmatter."""
    safe_desc = description.replace("\n", " ").strip()[:512]
    # Use a YAML double-quoted scalar to be safe with special chars like ':',
    # '#', leading whitespace and Unicode — without the document terminator
    # that ``yaml.safe_dump`` adds to scalars.
    encoded = safe_desc.replace("\\", "\\\\").replace('"', '\\"')
    block = f'---\ndescription: "{encoded}"\n---\n'
    if body.startswith("\n"):
        body = body.lstrip("\n")
    return block + body


def strip_frontmatter(content: str) -> str:
    """Return *content* without its frontmatter block (if any)."""
    return parse_frontmatter(content).body


__all__ = [
    "FrontmatterParseResult",
    "parse_frontmatter",
    "serialize_frontmatter",
    "strip_frontmatter",
]
