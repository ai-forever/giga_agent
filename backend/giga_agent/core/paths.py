from __future__ import annotations

from functools import cache
from pathlib import Path

from giga_agent.conf import get_settings


def giga_agent_dir() -> Path:
    return get_settings().giga_agent_project_root


@cache
def ensure_giga_agent_dir() -> Path:
    d = giga_agent_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
