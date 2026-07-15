from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


MEMORY_ROOT = "/memories"

_TAG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class InvalidMemoryPathError(ValueError):
    """Raised when a path is not a valid /memories/... reference."""


@dataclass(frozen=True)
class ParsedMemoryPath:
    path: str  # canonical, e.g. /memories/tg_chat_123/foo.md
    tag: str | None  # None for global memories
    filename: str  # e.g. foo.md


def is_memory_path(raw: str) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    if not raw.startswith(MEMORY_ROOT):
        return False
    if raw == MEMORY_ROOT:
        return False
    tail = raw[len(MEMORY_ROOT) :]
    return tail.startswith("/")


def _validate_segment(segment: str, *, kind: str) -> None:
    if not segment:
        raise InvalidMemoryPathError(f"Empty {kind} segment is not allowed")
    if segment in {".", ".."}:
        raise InvalidMemoryPathError(
            f"Path traversal segment '{segment}' is not allowed"
        )
    if "/" in segment or "\\" in segment:
        raise InvalidMemoryPathError(
            f"Nested segments inside {kind} are not allowed: {segment!r}"
        )


def parse_memory_path(raw: str) -> ParsedMemoryPath:
    """Validate and decompose a /memories/... path into (tag, filename).

    Tag is the first segment after /memories/ if more than one segment follows;
    otherwise the path is treated as global (no tag).
    """
    if not is_memory_path(raw):
        raise InvalidMemoryPathError(
            f"Path {raw!r} is not a memory path (must start with {MEMORY_ROOT}/)"
        )

    posix = PurePosixPath(raw)
    parts = posix.parts  # ('/', 'memories', ...)
    if len(parts) < 3:
        raise InvalidMemoryPathError(f"Memory path {raw!r} has no filename")

    rest = parts[2:]
    for seg in rest:
        _validate_segment(seg, kind="path")

    if len(rest) == 1:
        return ParsedMemoryPath(path=raw, tag=None, filename=rest[0])

    if len(rest) > 2:
        raise InvalidMemoryPathError(
            f"Memory path {raw!r} is too deep — expected /memories/<tag>/<file> or /memories/<file>"
        )

    tag, filename = rest
    if not _TAG_RE.match(tag):
        raise InvalidMemoryPathError(
            f"Invalid tag {tag!r} — only [a-zA-Z0-9_-] allowed"
        )
    return ParsedMemoryPath(path=raw, tag=tag, filename=filename)


def is_about_file(parsed: ParsedMemoryPath) -> bool:
    return parsed.filename.lower() == "about.md"


def global_about_path() -> str:
    return f"{MEMORY_ROOT}/ABOUT.md"


def tagged_about_path(tag: str) -> str:
    return f"{MEMORY_ROOT}/{tag}/ABOUT.md"


__all__ = [
    "MEMORY_ROOT",
    "InvalidMemoryPathError",
    "ParsedMemoryPath",
    "is_memory_path",
    "parse_memory_path",
    "is_about_file",
    "global_about_path",
    "tagged_about_path",
]
