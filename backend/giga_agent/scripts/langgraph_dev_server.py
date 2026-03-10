"""
Subprocess entrypoint for `giga_agent dev`.

We run LangGraph dev server in a dedicated process group so the parent CLI can
reliably stop the whole reload/worker tree on Ctrl+C/SIGTERM.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import uvicorn

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger, setup_cli_logging

logger = get_logger(__name__)


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _patch_uvicorn_log_suppression(*, desired_level: str) -> None:
    """
    Ensure external log noise is suppressed and our logs keep the chosen level.

    Important: this must run in the same process that executes `run_server`,
    including the uvicorn reload supervisor process.
    """
    logging.root.setLevel(logging.WARNING)
    logging.getLogger("giga_agent").setLevel(desired_level)
    # LangGraph dev server emits a noisy warning when allow_blocking=True.
    # Suppress it at the logger level early (before any dictConfig).
    logging.getLogger("langgraph_runtime_inmem").setLevel(logging.ERROR)
    logging.getLogger("langgraph_runtime_inmem.queue").setLevel(logging.ERROR)

    orig_uvicorn_run = uvicorn.run

    def _uvicorn_run_with_suppression(*args, **kwargs):
        # Allow overriding the ASGI app target while still using LangGraph's
        # environment patching and server bootstrap logic.
        override_app = get_settings().giga_agent_langgraph_dev_uvicorn_app
        if override_app:
            args = (override_app, *args[1:])

        log_config = kwargs.get("log_config")
        if isinstance(log_config, dict):
            if "root" in log_config:
                log_config["root"]["level"] = "WARNING"
            if "loggers" not in log_config:
                log_config["loggers"] = {}
            log_config["loggers"]["giga_agent"] = {"level": desired_level}
            # Keep allow_blocking (needed for local dev) but suppress that logger's warnings.
            log_config["loggers"]["langgraph_runtime_inmem"] = {"level": "ERROR"}
            log_config["loggers"]["langgraph_runtime_inmem.queue"] = {"level": "ERROR"}
        return orig_uvicorn_run(*args, **kwargs)

    uvicorn.run = _uvicorn_run_with_suppression


def _build_reload_excludes() -> list[str]:
    """
    Build reload excludes for uvicorn watchfiles.

    Uvicorn treats excludes that exist as directories specially (exclude_dirs) and compares
    them against absolute changed-path parents. Relative directory paths won't match, and
    non-existent absolute paths can be misclassified as glob patterns (which can raise
    NotImplementedError in Python's Path.match for absolute patterns).
    """
    cwd = Path.cwd()

    candidates = [
        cwd / ".giga_agent",
        cwd / ".langgraph_api",
    ]

    excludes: list[str] = []
    seen: set[str] = set()
    for p in candidates:
        try:
            if not p.is_dir():
                continue
            resolved = str(p.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        excludes.append(resolved)
    return excludes


def main() -> int:
    try:
        from langgraph_api.cli import run_server  # type: ignore
    except Exception as e:
        logger.exception("Failed to import langgraph_api.cli.run_server")
        print(f"Could not import langgraph_api.cli.run_server: {e}", file=sys.stderr)
        return 1

    settings = get_settings()
    host = settings.giga_agent_langgraph_dev_host
    port = settings.giga_agent_langgraph_dev_port
    reload_enabled = settings.giga_agent_langgraph_dev_reload
    log_level = settings.giga_agent_log_level

    graphs_json = settings.giga_agent_langgraph_dev_graphs_json
    auth_path = settings.giga_agent_langgraph_dev_auth_path
    http_app = settings.giga_agent_langgraph_dev_http_app
    http_config_json = settings.giga_agent_langgraph_dev_http_config_json

    try:
        graphs = json.loads(graphs_json)
        if not isinstance(graphs, dict):
            raise TypeError("graphs must be a JSON object")
    except Exception as e:
        print(
            f"Invalid graphs JSON in GIGA_AGENT_LANGGRAPH_DEV_GRAPHS_JSON: {e}",
            file=sys.stderr,
        )
        return 2

    http_config: dict[str, object] = {"app": http_app}
    if http_config_json:
        try:
            parsed_http_config = json.loads(http_config_json)
            if not isinstance(parsed_http_config, dict):
                raise TypeError("http config must be a JSON object")
            http_config = parsed_http_config
        except Exception as e:
            print(
                f"Invalid http config JSON in GIGA_AGENT_LANGGRAPH_DEV_HTTP_CONFIG_JSON: {e}",
                file=sys.stderr,
            )
            return 2

    setup_cli_logging(log_level)
    _patch_uvicorn_log_suppression(desired_level=log_level)
    reload_excludes = _build_reload_excludes()

    run_server(
        host,
        port,
        reload_enabled,
        graphs,
        n_jobs_per_worker=min(int(os.getenv("N_JOBS_PER_WORKER", 6)), 6),
        reload_excludes=reload_excludes,
        auth={"path": auth_path},
        http=http_config,
        allow_blocking=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
