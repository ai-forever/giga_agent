"""
CLI package for giga_agent.

Public surface is kept compatible with the historical `giga_agent.cli` module:
tests and external users can still import/patch `CLIException`, `dev`,
`load_graph_and_app_from_string`, `apply_migrations`, etc.
"""

from __future__ import annotations

import asyncio as asyncio

from .migrations.common import apply_migrations
from .types import CLIException, LogLevel
from .utils.imports import load_agent_from_string, load_graph_and_app_from_string

# Keep `dev` importable from `giga_agent.cli` (used in tests).
from .commands.dev import dev  # noqa: E402

# Typer application (entrypoint for console script).
from .app import app  # noqa: E402

__all__ = [
    "CLIException",
    "LogLevel",
    "app",
    "apply_migrations",
    "asyncio",
    "dev",
    "load_agent_from_string",
    "load_graph_and_app_from_string",
]
