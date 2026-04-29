from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from giga_agent.sandbox.secure_exec.errors import SandboxAccessDeniedError

NetworkMode = Literal["host", "none"]


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
