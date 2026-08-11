"""Shared test runtime isolation."""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path


_TEST_RUNTIME_PARENT = Path(tempfile.mkdtemp(prefix="giga-agent-tests-"))
_TEST_RUNTIME_ROOT = _TEST_RUNTIME_PARENT / ".giga_agent"
_TEST_DATABASE_PATH = _TEST_RUNTIME_ROOT / "db" / "local.db"
_TEST_DATABASE_PATH.parent.mkdir(parents=True)

# pytest imports this module before test collection. Set both settings so tests
# cannot fall back to backend/.giga_agent or a developer-provided database URL.
os.environ["GIGA_AGENT_PROJECT_ROOT"] = str(_TEST_RUNTIME_ROOT)
os.environ["GIGA_AGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DATABASE_PATH}"

from giga_agent.conf import reset_settings_cache  # noqa: E402
from giga_agent.core.paths import ensure_giga_agent_dir  # noqa: E402


reset_settings_cache()
ensure_giga_agent_dir.cache_clear()


def pytest_sessionfinish(session, exitstatus):
    """Release SQLite resources and remove the isolated runtime root."""
    del session, exitstatus

    try:
        from giga_agent.core.db import dispose_engine

        asyncio.run(dispose_engine())
    finally:
        shutil.rmtree(_TEST_RUNTIME_PARENT, ignore_errors=True)
