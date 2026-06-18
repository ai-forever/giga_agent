#!/usr/bin/env python3
"""Guard docs-only scope and Pages workflow merge-readiness."""

from __future__ import annotations

import pathlib
import subprocess
import sys

ALLOWED_PREFIXES = (
    "docs-site/",
    ".github/workflows/check-docs-version.yml",
    ".github/workflows/deploy-docs.yml",
)
FORBIDDEN_PREFIXES = ("backend/", "front/")
FORBIDDEN_EXACT = {"README.md"}
FORBIDDEN_MEDIA_PARTS = ("docs-site/static/img/examples/", "docs/images/examples/")


def fail(errors: list[str]) -> None:
    print("\n❌ Non-goal guard failed:\n")
    for err in errors:
        print(f"  - {err}")
    print()
    sys.exit(1)


def changed_files(repo: pathlib.Path) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "main...HEAD"], cwd=repo, text=True
        )
        files = [line.strip() for line in out.splitlines() if line.strip()]
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
            if path and path not in files:
                files.append(path)
        return files
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_non_goals.py <repo-root>")
        sys.exit(2)
    repo = pathlib.Path(sys.argv[1]).resolve()
    errors: list[str] = []
    files = changed_files(repo)
    for path in files:
        if path in FORBIDDEN_EXACT:
            errors.append(f"root README rewrite is out of scope: {path}")
        if path.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"backend/front behavior path is out of scope: {path}")
        if any(part in path for part in FORBIDDEN_MEDIA_PARTS):
            errors.append(f"screenshot/example media regeneration is out of scope: {path}")
        if not path.startswith(ALLOWED_PREFIXES) and path not in FORBIDDEN_EXACT:
            # Planning files are outside product repo and normally don't appear here.
            errors.append(f"unexpected changed path outside docs scope: {path}")

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
