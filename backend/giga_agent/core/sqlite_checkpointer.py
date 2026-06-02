"""Custom SQLite checkpointer for the local dev server.

langgraph-api loads this via the ``checkpointer`` config
(``{"backend": "custom", "path": "..."}``). The path must be the dotted form
``giga_agent.core.sqlite_checkpointer.create_checkpointer`` — langgraph's loader
splits a dotless path on the last ``.`` and would mis-parse a ``module:func``
form here.

The returned async context manager is entered once (per event loop) by
``_CustomCheckpointerAdapter`` and kept open for the server lifetime.
``AsyncSqliteSaver`` creates its tables lazily on first use, so no explicit
``setup()`` call is needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from giga_agent.core.paths import ensure_giga_agent_dir

# Config dict consumed by langgraph_api: pass as ``run_server(checkpointer=...)``.
CHECKPOINTER_CONFIG: dict[str, str] = {
    "backend": "custom",
    "path": "giga_agent.core.sqlite_checkpointer.create_checkpointer",
}


def checkpointer_db_path() -> str:
    """Resolve the SQLite file path under the giga_agent project dir.

    A real file (never ``:memory:``) is required: under ``--reload`` the server
    runs in a worker subprocess, so an in-memory DB would not survive restarts.
    """
    override = os.getenv("GIGA_AGENT_CHECKPOINTER_SQLITE_PATH")
    if override:
        Path(override).expanduser().parent.mkdir(parents=True, exist_ok=True)
        return str(Path(override).expanduser())
    return str(ensure_giga_agent_dir() / "checkpoints.sqlite")


def create_checkpointer():
    """Factory referenced by ``CHECKPOINTER_CONFIG['path']``.

    Returns an async context manager; langgraph's adapter enters it and closes
    it on shutdown.
    """
    return AsyncSqliteSaver.from_conn_string(checkpointer_db_path())
