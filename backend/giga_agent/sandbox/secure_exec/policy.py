from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from giga_agent.sandbox.secure_exec.errors import SandboxAccessDeniedError

NetworkMode = Literal["host", "none"]


def default_package_cache_write_roots() -> list[Path]:
    """Well-known cache/data directories used by popular package managers and
    build toolchains.

    Covers both cache (downloaded artefacts) and data (installed tools, global
    stores) locations.  On macOS the XDG-style paths live under ~/Library;
    on Linux they follow $XDG_CACHE_HOME / $XDG_DATA_HOME conventions.

    Returned paths are resolved; non-existing directories are included so that
    the sandbox profile is ready when a tool creates them on first run.
    """
    home = Path.home()
    is_darwin = platform.system() == "Darwin"

    if is_darwin:
        xdg_cache = home / "Library" / "Caches"
        xdg_data = home / "Library" / "Application Support"
    else:
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME") or (home / ".cache"))
        xdg_data = Path(
            os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share")
        )

    tmpdir = Path(tempfile.gettempdir())

    roots: list[Path] = [
        # ── Temp directories (used by virtually every build tool) ──
        Path("/tmp"),
        tmpdir,
        # ── Node.js ecosystem (npm / npx / yarn / pnpm / bun) ──
        home / ".npm",
        home / ".yarn",
        home / ".yarnrc",
        home / ".pnpm-store",
        home / ".bun",
        home / ".node-gyp",
        home / ".local" / "share" / "pnpm",
        xdg_cache / "yarn",
        xdg_cache / "pnpm",
        xdg_cache / "bun",
        xdg_data / "pnpm",
        # ── Python (pip / uv / uvx / pipx) ──
        xdg_cache / "pip",
        xdg_cache / "uv",
        xdg_data / "uv",
        xdg_data / "pipx",
        home / ".local",
        # ── Rust ──
        home / ".cargo",
        home / ".rustup",
        # ── JVM (Gradle / Maven / SBT) ──
        home / ".gradle",
        home / ".m2",
        home / ".ivy2",
        home / ".sbt",
        # ── Go ──
        xdg_cache / "go-build",
        # ── Ruby ──
        home / ".gem",
        home / ".bundle",
        # ── .NET ──
        home / ".nuget",
        home / ".dotnet",
        # ── PHP ──
        home / ".composer",
        # ── Dart / Flutter ──
        home / ".pub-cache",
    ]

    if is_darwin:
        roots.append(home / "Library" / "pnpm")

    return [p.resolve() for p in roots]


def normalize_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _normalize_path_list(value: Any) -> list[Path]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, Path)):
        return [normalize_path(value)]
    return [normalize_path(item) for item in value]


def is_path_within(path: Path, root: Path) -> bool:
    if root == Path("/"):
        return path.is_absolute()
    return path == root or root in path.parents


class SandboxAccessPolicy(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_default=True)

    workspace_root: Path
    runtime_roots: list[Path] = Field(default_factory=list)
    read_roots: list[Path] = Field(default_factory=lambda: [Path("/")])
    write_roots: list[Path] = Field(default_factory=list)
    deny_roots: list[Path] = Field(default_factory=list)
    cwd: Path | None = None
    network_mode: NetworkMode = "host"

    @field_validator("workspace_root", "cwd", mode="before")
    @classmethod
    def _validate_optional_path(cls, value: Any) -> Any:
        if value is None:
            return None
        return normalize_path(value)

    @field_validator(
        "runtime_roots",
        "read_roots",
        "write_roots",
        "deny_roots",
        mode="before",
    )
    @classmethod
    def _validate_path_list(cls, value: Any) -> list[Path]:
        return _normalize_path_list(value)

    @field_validator("network_mode")
    @classmethod
    def _validate_network_mode(cls, value: str) -> str:
        if value not in {"host", "none"}:
            raise ValueError("network_mode must be 'host' or 'none'")
        return value

    def readable_roots(self) -> list[Path]:
        return _dedupe_paths([*self.read_roots, *self.writable_roots()])

    def writable_roots(self) -> list[Path]:
        return _dedupe_paths(
            [self.workspace_root, *self.runtime_roots, *self.write_roots]
        )

    def can_read(self, path: Path | str) -> bool:
        candidate = normalize_path(path)
        if self._is_denied(candidate) and not self._is_within_any(
            candidate, self.writable_roots()
        ):
            return False
        return self._is_within_any(candidate, self.readable_roots())

    def can_write(self, path: Path | str) -> bool:
        return self._is_within_any(normalize_path(path), self.writable_roots())

    def can_delete(self, path: Path | str) -> bool:
        return self.can_write(path)

    def assert_can_read(self, path: Path | str) -> Path:
        candidate = normalize_path(path)
        if not self.can_read(candidate):
            raise SandboxAccessDeniedError(f"Read access denied: {candidate}")
        return candidate

    def assert_can_write(self, path: Path | str) -> Path:
        candidate = normalize_path(path)
        if not self.can_write(candidate):
            raise SandboxAccessDeniedError(f"Write access denied: {candidate}")
        return candidate

    def assert_can_delete(self, path: Path | str) -> Path:
        candidate = normalize_path(path)
        if not self.can_delete(candidate):
            raise SandboxAccessDeniedError(f"Delete access denied: {candidate}")
        return candidate

    def assert_valid_cwd(self, *, require_writable: bool = False) -> Path:
        cwd = normalize_path(self.cwd or self.workspace_root)
        if require_writable:
            self.assert_can_write(cwd)
        elif not self.can_read(cwd):
            raise SandboxAccessDeniedError(f"Working directory access denied: {cwd}")
        return cwd

    def fingerprint(self) -> str:
        payload = {
            "workspace_root": str(self.workspace_root),
            "runtime_roots": [str(path) for path in self.runtime_roots],
            "read_roots": [str(path) for path in self.read_roots],
            "write_roots": [str(path) for path in self.write_roots],
            "deny_roots": [str(path) for path in self.deny_roots],
            "network_mode": self.network_mode,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _is_denied(self, path: Path) -> bool:
        return self._is_within_any(path, self.deny_roots)

    @staticmethod
    def _is_within_any(path: Path, roots: list[Path]) -> bool:
        return any(is_path_within(path, root) for root in roots)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    return list(dict.fromkeys(paths))
