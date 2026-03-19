from __future__ import annotations

from pathlib import Path

from hatchling.metadata.plugin.interface import MetadataHookInterface


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict) -> None:
        root_readme = Path(self.root).parent / "README.md"
        metadata["readme"] = {
            "text": root_readme.read_text(encoding="utf-8"),
            "content-type": "text/markdown",
        }
