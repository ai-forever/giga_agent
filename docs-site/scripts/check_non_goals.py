#!/usr/bin/env python3
"""Guard docs-only scope and Pages workflow merge-readiness."""

from __future__ import annotations

import pathlib
import subprocess
import sys

ALLOWED_PREFIXES = (
    "docs-site/",
    "README.md",
    ".github/workflows/check-docs-version.yml",
    ".github/workflows/deploy-docs.yml",
)
FORBIDDEN_PREFIXES = ("backend/", "front/")
# Untracked build/download artifacts created by the docs-contracts workflow
# (e.g. the `giga-agent` wheel extracted into `_pkg/` for the PyPI contract
# check). They are not part of the change set and must not fail the scope guard.
IGNORED_UNTRACKED_PREFIXES = ("_pkg/",)
# Gallery images are cleaned historical screenshots; replacing an existing one
# silently is forbidden. Adding new files is a normal documentation change.
PROTECTED_MEDIA_PARTS = ("docs-site/static/img/examples/", "docs/images/examples/")


def fail(errors: list[str]) -> None:
    print("\n❌ Non-goal guard failed:\n")
    for err in errors:
        print(f"  - {err}")
    print()
    sys.exit(1)


def base_ref(repo: pathlib.Path) -> str:
    """Pick an existing base ref for the diff.

    On a pull-request checkout the local `main` branch usually does not exist
    (only `origin/main`), so prefer the remote-tracking ref and fall back to
    the local branch for pushes/local runs.
    """
    for candidate in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", candidate],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    return "main"


def changed_files(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (all changed paths, paths of modified/renamed tracked files)."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-status", f"{base_ref(repo)}...HEAD"],
            cwd=repo,
            text=True,
        )
        files: list[str] = []
        modified: list[str] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status, path = parts[0], parts[-1]
            files.append(path)
            if status[:1] in {"M", "R"}:
                modified.append(path)
        # Include unstaged/staged files for local verification before commit.
        out2 = subprocess.check_output(
            ["git", "status", "--short", "--untracked-files=all"], cwd=repo, text=True
        )
        for line in out2.splitlines():
            if not line.strip():
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path.startswith(IGNORED_UNTRACKED_PREFIXES):
                continue
            if path and path not in files:
                files.append(path)
        return files, modified
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_non_goals.py <repo-root>")
        sys.exit(2)
    repo = pathlib.Path(sys.argv[1]).resolve()
    errors: list[str] = []
    files, modified = changed_files(repo)
    for path in files:
        if path.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"backend/front behavior path is out of scope: {path}")
        if not path.startswith(ALLOWED_PREFIXES):
            # Planning files are outside product repo and normally don't appear here.
            errors.append(f"unexpected changed path outside docs scope: {path}")
    for path in modified:
        if any(part in path for part in PROTECTED_MEDIA_PARTS):
            errors.append(
                f"existing gallery screenshot must not be replaced silently: {path}"
            )

    workflow = (repo / ".github/workflows/deploy-docs.yml").read_text(encoding="utf-8")
    for required in ["branches: [main]", "docs-site/**", "npm ci", "npm run typecheck", "npm run build", "upload-pages-artifact"]:
        if required not in workflow:
            errors.append(f"deploy-docs workflow missing merge-readiness marker: {required}")

    if errors:
        fail(errors)
    print("✅ Non-goal guard and Pages workflow merge-readiness check passed.")
    print(f"  changed files checked: {len(files)}")


if __name__ == "__main__":
    main()
