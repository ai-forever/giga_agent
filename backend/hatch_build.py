from __future__ import annotations

import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        """
        Ensure the built frontend UI is included in both sdist and wheel.

        Strategy:
        - If `giga_agent/ui_dist` already exists in the project tree, we assume it
          will be packaged normally as package data.
        - Otherwise, we try to include `../front/dist` into `giga_agent/ui_dist`.
        - If neither exists, we fail fast with a clear error.
        """
        pkg_ui_dist = os.path.join(self.root, "giga_agent", "ui_dist")
        if os.path.isdir(pkg_ui_dist) and os.listdir(pkg_ui_dist):
            # `packages = ["giga_agent"]` does not guarantee non-Python files are
            # included in the wheel. Force-include the directory explicitly.
            force_include = build_data.setdefault("force_include", {})
            force_include[pkg_ui_dist] = "giga_agent/ui_dist"

            # Editable installs (PEP 660) use a separate build-data key.
            force_include_editable = build_data.setdefault("force_include_editable", {})
            force_include_editable[pkg_ui_dist] = "giga_agent/ui_dist"
            return

        front_dist = os.path.abspath(os.path.join(self.root, "..", "front", "dist"))
        if os.path.isdir(front_dist) and os.listdir(front_dist):
            # Standard wheels/sdists use `force_include`.
            force_include = build_data.setdefault("force_include", {})
            force_include[front_dist] = "giga_agent/ui_dist"

            # Editable installs (PEP 660) use a separate build-data key.
            force_include_editable = build_data.setdefault("force_include_editable", {})
            force_include_editable[front_dist] = "giga_agent/ui_dist"
            return

        raise RuntimeError(
            "UI bundle not found. Expected either `backend/giga_agent/ui_dist` "
            "(pre-synced) or `front/dist` (built). Build the frontend first "
            "(e.g. in `front/`: `npm ci && npm run build`) or sync it into "
            "`backend/giga_agent/ui_dist` before packaging."
        )

