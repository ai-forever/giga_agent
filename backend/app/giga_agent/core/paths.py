from __future__ import annotations

import os
from functools import cache
from pathlib import Path


def giga_agent_dir() -> Path:
    return os.getenv("GIGA_AGENT_PROJECT_ROOT", Path.cwd() / ".giga_agent")


@cache
def ensure_giga_agent_dir() -> Path:
    d = giga_agent_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
