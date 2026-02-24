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

import uvicorn

from giga_agent.core.logging import get_logger, setup_cli_logging
from giga_agent.utils.blockbuster import _enable_blockbuster

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


def main() -> int:
    try:
        from langgraph_api.cli import run_server  # type: ignore
    except Exception as e:
        logger.exception("Failed to import langgraph_api.cli.run_server")
        print(f"Could not import langgraph_api.cli.run_server: {e}", file=sys.stderr)
        return 1

    host = os.getenv("GIGA_AGENT_LANGGRAPH_DEV_HOST", "127.0.0.1")
    port = int(os.getenv("GIGA_AGENT_LANGGRAPH_DEV_PORT", "9090"))
    reload_enabled = _is_truthy_env(os.getenv("GIGA_AGENT_LANGGRAPH_DEV_RELOAD", "1"))
    log_level = (os.getenv("GIGA_AGENT_LANGGRAPH_DEV_LOG_LEVEL") or "INFO").upper()

    graphs_json = os.getenv("GIGA_AGENT_LANGGRAPH_DEV_GRAPHS_JSON") or "{}"
    auth_path = os.getenv("GIGA_AGENT_LANGGRAPH_DEV_AUTH_PATH") or ""
    http_app = os.getenv("GIGA_AGENT_LANGGRAPH_DEV_HTTP_APP") or ""

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

    setup_cli_logging(log_level)
    _patch_uvicorn_log_suppression(desired_level=log_level)

    run_server(
        host,
        port,
        reload_enabled,
        graphs,
        auth={"path": auth_path},
        http={"app": http_app},
        allow_blocking=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
