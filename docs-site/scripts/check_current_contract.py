#!/usr/bin/env python3
"""Check that current/main docs match the checked-out repository state.

This script intentionally validates the current repository source tree, not the
published PyPI wheel. It complements check_pypi_contract.py, which remains the
source-of-truth check for stable release documentation.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

CURRENT_ONLY_MODULES = {
    "IOModule",
    "MemoryModule",
    "SkillsModule",
    "DeepResearchModule",
}


def fail(errors: list[str]) -> None:
    print("\n❌ Current/main documentation does not match repository state:\n")
    for err in errors:
        print(f"  - {err}")
    print("\nUpdate docs-site/docs/** or the current contract check.\n")
    sys.exit(1)


def registered_module_classes(repo: pathlib.Path, errors: list[str]) -> list[str]:
    source = repo / "backend/giga_agent/agents/giga_agent.py"
    if not source.is_file():
        errors.append(f"missing current GigaAgent source: {source}")
        return []
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_modules":
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    if child.func.id.endswith("Module"):
                        found.append(child.func.id)
            break
    if not found:
        errors.append("GigaAgent.get_modules() has no module class calls")
    return found


def read_current_docs(repo: pathlib.Path, errors: list[str]) -> str:
    docs_root = repo / "docs-site/docs"
    if not docs_root.is_dir():
        errors.append(f"missing current docs root: {docs_root}")
        return ""
    parts: list[str] = []
    for path in sorted(docs_root.rglob("*.md")) + sorted(docs_root.rglob("*.mdx")):
        parts.append(f"\n<!-- {path.relative_to(repo)} -->\n")
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_current_contract.py <repo-root>")
        sys.exit(2)
    repo = pathlib.Path(sys.argv[1]).resolve()
    errors: list[str] = []

    modules = registered_module_classes(repo, errors)
    docs_text = read_current_docs(repo, errors)

    if modules and docs_text:
        if str(len(modules)) not in docs_text:
            errors.append(
                f"current docs do not mention current registered module count {len(modules)}"
            )
        missing = [module for module in modules if module not in docs_text]
        if missing:
            errors.append(f"current docs do not mention modules: {missing}")
        missing_current_only = sorted(CURRENT_ONLY_MODULES - set(modules))
        if missing_current_only:
            errors.append(
                "contract expected current-only modules absent from source: "
                f"{missing_current_only}"
            )
        stale_patterns = [
            r"загружает\s+12\s+модул",
            r"Активные модули версии 0\.1\.9",
            r"Эта страница описывает стандартного агента из `giga-agent==0\.1\.9`",
            r"has_изолированная\s+среда",
            r"`изолированная\s+среда`",
        ]
        for pattern in stale_patterns:
            if re.search(pattern, docs_text, flags=re.IGNORECASE):
                errors.append(
                    f"current docs still contain stable/PyPI-only wording matching {pattern!r}"
                )
        current_markers = ["current/main", "текущ", "репозитори", "main"]
        if not any(marker.lower() in docs_text.lower() for marker in current_markers):
            errors.append("current docs do not visibly identify themselves as current/main repository docs")

    if errors:
        fail(errors)

    print("✅ Current/main documentation matches checked-out repository contract.")
    print(f"  registered modules: {len(modules)}")


if __name__ == "__main__":
    main()
