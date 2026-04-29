from __future__ import annotations

from collections.abc import Callable


def build_resource_preexec_fn() -> Callable[[], None] | None:
    """Placeholder for future per-process resource limits.

    Linux/macOS file access is enforced by the OS-specific launchers. Resource
    limits can be added here without changing LocalJupyter integration points.
    """

    return None
