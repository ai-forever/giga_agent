#!/usr/bin/env python3
"""Check published docs RU/EN structure parity within each docs version.

Stable and current sidebars are allowed to differ: features shipped after the
stable release are documented only in current, and pages retired from current
may legitimately stay in stable. RU and EN must expose the same page set
within every version.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

SIDE_BAR_ITEM_RE = re.compile(r"'([^']+/[^']+|overview|examples/index)'")


def fail(errors: list[str]) -> None:
    print("\n❌ Documentation matrix parity check failed:\n")
    for err in errors:
        print(f"  - {err}")
    print()
    sys.exit(1)


def current_sidebar_ids(site: pathlib.Path) -> list[str]:
    text = (site / "sidebars.ts").read_text(encoding="utf-8")
    ids = [
        doc_id
        for doc_id in SIDE_BAR_ITEM_RE.findall(text)
        if not doc_id.startswith("@")
    ]
    return sorted(dict.fromkeys(ids))


def versioned_sidebar_ids(site: pathlib.Path, version: str) -> list[str]:
    data = json.loads(
        (site / f"versioned_sidebars/version-{version}-sidebars.json").read_text(
            encoding="utf-8"
        )
    )
    out: list[str] = []

    def walk(items):
        for item in items:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "doc" and "id" in item:
                    out.append(item["id"])
                if "items" in item:
                    walk(item["items"])

    walk(data["docs"])
    return sorted(dict.fromkeys(out))


def doc_exists(root: pathlib.Path, doc_id: str) -> bool:
    return (root / f"{doc_id}.md").is_file() or (root / f"{doc_id}.mdx").is_file()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_docs_matrix.py <docs-site-root>")
        sys.exit(2)
    site = pathlib.Path(sys.argv[1]).resolve()
    version = json.loads((site / "docs-version.json").read_text(encoding="utf-8"))["version"]
    errors: list[str] = []

    current_ids = current_sidebar_ids(site)
    stable_ids = versioned_sidebar_ids(site, version)

    matrix = {
        "current": (
            current_ids,
            {
                "ru-current": site / "docs",
                "en-current": site / "i18n/en/docusaurus-plugin-content-docs/current",
            },
        ),
        "stable": (
            stable_ids,
            {
                "ru-stable": site / f"versioned_docs/version-{version}",
                "en-stable": site
                / f"i18n/en/docusaurus-plugin-content-docs/version-{version}",
            },
        ),
    }
    for _, (ids, roots) in matrix.items():
        for label, root in roots.items():
            if not root.is_dir():
                errors.append(
                    f"missing docs matrix root {label}: {root.relative_to(site)}"
                )
                continue
            missing = [doc_id for doc_id in ids if not doc_exists(root, doc_id)]
            if missing:
                errors.append(f"{label} missing published docs: {missing}")

    # Maintenance-only pages must stay out of sidebar parity unless deliberately published.
    maintenance = site / "docs/examples/_maintenance/screenshot-provenance.md"
    if maintenance.exists() and "examples/_maintenance/screenshot-provenance" in current_ids:
        errors.append("maintenance-only screenshot provenance page is unexpectedly published in sidebar")

    if errors:
        fail(errors)

    print("✅ Documentation matrix has matching RU/EN page IDs within each version.")
    print(f"  current docs: {len(current_ids)}, stable docs: {len(stable_ids)}")
    cur_only = sorted(set(current_ids) - set(stable_ids))
    if cur_only:
        print(f"  current-only (features shipped after {version}): {cur_only}")


if __name__ == "__main__":
    main()
