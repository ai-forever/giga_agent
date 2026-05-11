import os
from typing import Final

from cashews import cache
from giga_agent.conf import get_settings

_DEFAULT_REDIS_URL: Final[str] = "redis://localhost:6379/0"
_DEFAULT_MEM_URL: Final[str] = "mem://"

_is_setup: bool = False


def setup_cache() -> None:
    """
    Initialize cashews cache backend.

    Idempotent: safe to call multiple times.
    """
    global _is_setup
    if _is_setup:
        return

    runtime = get_settings().giga_agent_runtime
    if runtime in ("local", "cli"):
        cache.setup(_DEFAULT_MEM_URL, size=2048)
    else:
        cache.setup(os.getenv("REDIS_URL", _DEFAULT_REDIS_URL))

    _is_setup = True
