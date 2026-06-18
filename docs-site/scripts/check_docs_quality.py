#!/usr/bin/env python3
"""Lightweight docs quality scans for language leakage and Russian-first glossary."""

from __future__ import annotations

import pathlib
import json
import re
import sys
from urllib.parse import unquote, urlparse

SCAFFOLD_RE = re.compile(r"Welcome to Docusaurus|TODO|FIXME|lorem|Edit this page|This is a draft", re.I)
CONTRACT_DRIFT_RE = re.compile(
    r"user\.sandbox_id|has_изолированная\s+среда|`изолированная\s+среда`|изолированная\s+среда-security",
    re.I,
)
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]{3,}")
GLOSSARY_RE = re.compile(r"\b(workflow|build|deploy|current-main|upcoming|runtime|sandbox|tools|frontend|backend|legacy)\b", re.I)
FENCED_BLOCK_RE = re.compile(r"```.*?```", re.S)
MARKDOWN_LINK_TARGET_RE = re.compile(r"\]\([^)]+\)")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

ALLOWED_GLOSSARY_CONTEXT_RE = re.compile(
    r"(`[^`]*`|Docker|Docker Compose|PyPI|GitHub|FastAPI|LangGraph|Qdrant|Redis|PostgreSQL|REPL|RAG|MCP|API|CLI)",
    re.I,
)


def iter_docs(root: pathlib.Path):
    for pattern in ("*.md", "*.mdx", "*.json", "*.ts", "*.tsx"):
        yield from root.rglob(pattern)


def json_message_text(path: pathlib.Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    messages: list[str] = []
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                messages.append(value["message"])
    return "\n".join(messages)


def fail(errors: list[str]) -> None:
    print("\n❌ Documentation quality check failed:\n")
    for err in errors:
        print(f"  - {err}")
    print()
    sys.exit(1)


def is_local_docs_link(target: str) -> bool:
    target = target.strip()
    if not target or target.startswith("#"):
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and not target.startswith("/")


def local_link_exists(path: pathlib.Path, target: str) -> bool:
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
    if not clean:
        return True
    candidate = (path.parent / clean).resolve()
    if candidate.is_file():
        return True
    if candidate.suffix:
        return False
    return (
        candidate.with_suffix(".md").is_file()
        or candidate.with_suffix(".mdx").is_file()
        or (candidate / "index.md").is_file()
        or (candidate / "index.mdx").is_file()
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_docs_quality.py <docs-site-root>")
        sys.exit(2)
    site = pathlib.Path(sys.argv[1]).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    search_roots = [p for p in [site / "docs", site / "versioned_docs", site / "i18n"] if p.exists()]
    for root in search_roots:
        for path in iter_docs(root):
            text = (
                json_message_text(path)
                if path.suffix == ".json"
                else path.read_text(encoding="utf-8", errors="ignore")
            )
            rel = path.relative_to(site)
            if SCAFFOLD_RE.search(text):
                errors.append(f"scaffold/placeholder text in {rel}")
            if CONTRACT_DRIFT_RE.search(text):
                errors.append(f"code/link contract drift marker in {rel}")
            if str(rel).startswith("i18n/en/") and CYRILLIC_RE.search(text):
                errors.append(f"Cyrillic prose remains in English locale file {rel}")
            if path.suffix in {".md", ".mdx"}:
                for link in MARKDOWN_LINK_RE.finditer(text):
                    target = link.group(1)
                    if is_local_docs_link(target) and not local_link_exists(path, target):
                        line_no = text.count("\n", 0, link.start()) + 1
                        errors.append(f"broken local docs link in {rel}:{line_no}: {target}")
            if str(rel).startswith(("docs/", "versioned_docs/")):
                glossary_text = FENCED_BLOCK_RE.sub("", text)
                glossary_text = MARKDOWN_LINK_TARGET_RE.sub("]", glossary_text)
                for m in GLOSSARY_RE.finditer(glossary_text):
                    line_start = glossary_text.rfind("\n", 0, m.start()) + 1
                    line_end = glossary_text.find("\n", m.end())
                    if line_end == -1:
                        line_end = len(glossary_text)
                    line = glossary_text[line_start:line_end]
                    if not ALLOWED_GLOSSARY_CONTEXT_RE.search(line):
                        line_no = glossary_text.count("\n", 0, m.start()) + 1
                        warnings.append(f"{rel}:{line_no}: review glossary term {m.group(0)!r}")

    if errors:
        fail(errors)
    print("✅ No critical language/scaffold quality failures.")
    if warnings:
        print("\nGlossary review warnings:")
        for warning in warnings[:200]:
            print(f"  - {warning}")
        if len(warnings) > 200:
            print(f"  ... {len(warnings) - 200} more warnings")


if __name__ == "__main__":
    main()
