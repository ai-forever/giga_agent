from __future__ import annotations

from giga_agent.conf import get_settings
from giga_agent.memory.backends.base import (
    MemoryBackend,
    MemoryFileDTO,
    MemoryFileNotFoundError,
    MemoryFileExistsError,
)


def get_backend() -> MemoryBackend:
    """Return the configured backend instance based on runtime mode."""
    runtime = get_settings().giga_agent_runtime
    if runtime == "cli":
        from giga_agent.memory.backends.file import FileBackend

        return FileBackend()

    from giga_agent.memory.backends.db import DBBackend

    return DBBackend()


__all__ = [
    "MemoryBackend",
    "MemoryFileDTO",
    "MemoryFileNotFoundError",
    "MemoryFileExistsError",
    "get_backend",
]
