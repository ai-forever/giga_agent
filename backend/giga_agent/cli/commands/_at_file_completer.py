from __future__ import annotations

import os
import re
import time
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.document import Document

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".giga_agent",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".cache",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".parcel-cache",
        "target",
        ".idea",
        ".vscode",
        ".gradle",
        ".terraform",
        ".DS_Store",
    }
)

MAX_INDEX_FILES = 10_000
INDEX_TTL_SECONDS = 10.0
MAX_COMPLETIONS = 30

_AT_TOKEN_RE = re.compile(r"(?:^|\s)@([^\s]*)$")

_WORD_BOUNDARY_CHARS = "/-_. "


def _fuzzy_score(query: str, target: str) -> int | None:
    """Greedy left-to-right fuzzy match. Returns a score or None if no match.

    Higher score = better match. Bonuses for matches at the start of the
    target, at word boundaries (after / - _ . space), and for consecutive
    runs of matched characters.
    """
    if not query:
        return 0
    n = len(query)
    if n > len(target):
        return None

    score = 0
    qi = 0
    last_match = -2
    streak = 0
    for ti, ch in enumerate(target):
        if qi >= n:
            break
        if ch == query[qi]:
            char_score = 1
            if ti == last_match + 1:
                streak += 1
                char_score += 5 + streak
            else:
                streak = 0
                if ti == 0:
                    char_score += 8
                elif target[ti - 1] in _WORD_BOUNDARY_CHARS:
                    char_score += 6
            score += char_score
            last_match = ti
            qi += 1

    if qi < n:
        return None

    score -= (len(target) - n) // 16
    return score


class AtFileCompleter(Completer):
    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd
        self._index: list[str] = []
        self._indexed_at: float = 0.0

    def _build_index(self) -> list[str]:
        results: list[str] = []
        cwd_str = str(self._cwd)
        try:
            walker = os.walk(cwd_str, followlinks=False)
        except OSError:
            return results

        for dirpath, dirnames, filenames in walker:
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")
            ]

            for name in filenames:
                if name in EXCLUDED_DIR_NAMES:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    rel = os.path.relpath(full, cwd_str)
                except ValueError:
                    continue
                results.append(Path(rel).as_posix())
                if len(results) >= MAX_INDEX_FILES:
                    return results

        return results

    def _get_index(self) -> list[str]:
        now = time.monotonic()
        if not self._index or now - self._indexed_at > INDEX_TTL_SECONDS:
            self._index = self._build_index()
            self._indexed_at = now
        return self._index

    def get_completions(self, document: Document, complete_event):
        text_before = document.text_before_cursor
        match = _AT_TOKEN_RE.search(text_before)
        if not match:
            return

        query = match.group(1)
        start_position = -len(query)
        query_lower = query.lower()

        index = self._get_index()

        if not query_lower:
            candidates = sorted(index, key=str.lower)[:MAX_COMPLETIONS]
            for rel_path in candidates:
                yield self._make_completion(rel_path, start_position)
            return

        # Score by basename first (with a boost so basename hits outrank
        # path-only hits), then fall back to scoring against the full path.
        scored: list[tuple[int, int, str, str]] = []
        for rel_path in index:
            base_lower = Path(rel_path).name.lower()
            base_score = _fuzzy_score(query_lower, base_lower)
            if base_score is not None:
                scored.append((-(base_score + 100), 0, rel_path.lower(), rel_path))
                continue
            path_score = _fuzzy_score(query_lower, rel_path.lower())
            if path_score is not None:
                scored.append((-path_score, 1, rel_path.lower(), rel_path))

        scored.sort()
        for _, _, _, rel_path in scored[:MAX_COMPLETIONS]:
            yield self._make_completion(rel_path, start_position)

    @staticmethod
    def _make_completion(rel_path: str, start_position: int) -> Completion:
        return Completion(
            text=rel_path,
            start_position=start_position,
            display=[("class:at-file.symbol", "▸ "), ("class:at-file.path", rel_path)],
        )


def make_at_file_completer(cwd: Path) -> Completer:
    return ThreadedCompleter(AtFileCompleter(cwd))
