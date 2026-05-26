"""Helpers for locating skill manifest files."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

_SKILL_MANIFEST_PRIORITY = {
    "SKILL.md": 0,
    "skill.md": 1,
    "Skill.md": 2,
}


def is_skill_manifest_filename(filename: str) -> bool:
    return filename.lower() == "skill.md"


def _manifest_sort_key(filename: str) -> tuple[int, str, str]:
    return (
        _SKILL_MANIFEST_PRIORITY.get(filename, len(_SKILL_MANIFEST_PRIORITY)),
        filename.lower(),
        filename,
    )


def find_skill_manifest_path(directory: Path) -> Path | None:
    """Return one supported manifest file from a directory, if present."""
    matches = [
        child
        for child in directory.iterdir()
        if child.is_file() and is_skill_manifest_filename(child.name)
    ]
    if not matches:
        return None
    return min(matches, key=lambda path: _manifest_sort_key(path.name))


def select_skill_manifest_file(relative_paths: Iterable[str]) -> str | None:
    """Return one root-level manifest path from a skill file listing."""
    matches = [
        path
        for path in relative_paths
        if "/" not in path
        and "\\" not in path
        and is_skill_manifest_filename(Path(path).name)
    ]
    if not matches:
        return None
    return min(matches, key=lambda path: _manifest_sort_key(Path(path).name))
