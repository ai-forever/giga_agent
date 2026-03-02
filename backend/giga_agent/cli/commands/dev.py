from __future__ import annotations

import importlib
import inspect
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Annotated

import typer

from giga_agent.conf import reset_settings_cache
from giga_agent.core.logging import get_logger, setup_cli_logging

from ._langgraph_config import build_langgraph_runtime_config
from ..types import LogLevel

logger = get_logger(__name__)


def _terminate_process_group(proc: subprocess.Popen[object], *, force: bool) -> None:
    if proc.poll() is not None:
        return

    if os.name == "nt":
        if force:
            proc.kill()
        else:
            proc.terminate()
        return

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        pgid = int(os.getpgid(proc.pid))
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return
    except Exception:
        return


def _run_langgraph_server_in_subprocess(
    *,
    host: str,
    port: int,
    reload: bool,
    graphs: dict[str, str],
    auth_path: str,
    http_config: dict[str, object],
    log_level: str,
) -> int:
    env = os.environ.copy()
    env["GIGA_AGENT_LANGGRAPH_DEV_HOST"] = host
    env["GIGA_AGENT_LANGGRAPH_DEV_PORT"] = str(port)
    env["GIGA_AGENT_LANGGRAPH_DEV_RELOAD"] = "1" if reload else "0"
    env["GIGA_AGENT_LANGGRAPH_DEV_GRAPHS_JSON"] = json.dumps(graphs)
    env["GIGA_AGENT_LANGGRAPH_DEV_AUTH_PATH"] = auth_path
    env["GIGA_AGENT_LANGGRAPH_DEV_HTTP_APP"] = str(http_config.get("app", ""))
    env["GIGA_AGENT_LANGGRAPH_DEV_HTTP_CONFIG_JSON"] = json.dumps(http_config)
    env["GIGA_AGENT_LANGGRAPH_DEV_LOG_LEVEL"] = log_level
    from giga_agent.conf import GIGA_AGENT_UI

    if GIGA_AGENT_UI:
        env["GIGA_AGENT_LANGGRAPH_DEV_UVICORN_APP"] = (
            "giga_agent.scripts.combined_asgi:app"
        )
    else:
        env.pop("GIGA_AGENT_LANGGRAPH_DEV_UVICORN_APP", None)

    cmd = [sys.executable, "-m", "giga_agent.scripts.langgraph_dev_server"]
    proc = subprocess.Popen(cmd, env=env, start_new_session=True)
    logger.info(f"LangGraph dev server started (pid={proc.pid}). Press Ctrl+C to stop.")

    stop_event = threading.Event()
    force_stop_event = threading.Event()
    stop_requested_at: float | None = None

    def _request_stop(*_args: object) -> None:
        stop_event.set()

    try:
        signal.signal(signal.SIGTERM, _request_stop)
    except Exception:
        pass

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return int(rc)

            if stop_event.is_set():
                now = time.time()
                if force_stop_event.is_set():
                    logger.warning(
                        "Force-stopping LangGraph dev server (hard stop requested)..."
                    )
                    _terminate_process_group(proc, force=True)
                elif stop_requested_at is None:
                    stop_requested_at = now
                    logger.info("Stopping LangGraph dev server...")
                    _terminate_process_group(proc, force=False)
                elif now - stop_requested_at > 3.0:
                    logger.warning("Force-stopping LangGraph dev server...")
                    _terminate_process_group(proc, force=True)

            time.sleep(0.2)
    except KeyboardInterrupt:
        is_second_interrupt = stop_event.is_set()
        if is_second_interrupt:
            force_stop_event.set()
            logger.warning(
                "Force-stopping LangGraph dev server... (second Ctrl+C received)"
            )
        else:
            logger.info("Graceful stop requested. Press Ctrl+C again to force stop.")

        stop_event.set()
        _terminate_process_group(proc, force=is_second_interrupt)
        try:
            return int(proc.wait(timeout=2.5))
        except Exception:
            return 130


def dev(
    graph_and_app_path: Annotated[
        str,
        typer.Argument(
            help=("Path to graph and app, " "e.g. giga_agent.agents.run:graph:app")
        ),
    ] = "giga_agent.agents.run:graph:app",
    log_level: Annotated[
        LogLevel, typer.Option(help="Logging level", case_sensitive=False)
    ] = LogLevel.INFO,
    host: Annotated[str, typer.Option(help="Host to bind to")] = "localhost",
    port: Annotated[int, typer.Option(help="Port to bind to")] = 9090,
    no_reload: Annotated[bool, typer.Option(help="Disable auto-reload")] = False,
    frontend_url: Annotated[
        str, typer.Option(help="Frontend URL for /base hint")
    ] = "http://localhost:3000",
) -> None:
    """
    Development mode: start LangGraph dev server.
    Migrations and startup hooks are executed by FastAPI lifespan.
    """
    try:
        from langgraph_api.cli import run_server  # type: ignore
    except ImportError:
        py_version_msg = ""

        if sys.version_info < (3, 11):
            py_version_msg = (
                "\n\nNote: The in-mem server requires Python 3.11 or higher to be installed."
                f" You are currently using Python {sys.version_info.major}.{sys.version_info.minor}."
                ' Please upgrade your Python version before installing "langgraph-cli[inmem]".'
            )
        try:
            from importlib import util

            if not util.find_spec("langgraph_api"):
                raise Exception(
                    "Required package 'langgraph-api' is not installed.\n"
                    "Please install it with:\n\n"
                    '    pip install -U "langgraph-cli[inmem]"'
                    f"{py_version_msg}"
                )
        except ImportError:
            raise Exception(
                "Could not verify package installation. Please ensure Python is up to date and\n"
                "langgraph-cli is installed with the 'inmem' extra: pip install -U \"langgraph-cli[inmem]\""
                f"{py_version_msg}"
            )
        raise Exception(
            "Could not import run_server. This likely means your installation is incomplete.\n"
            "Please ensure langgraph-cli is installed with the 'inmem' extra: pip install -U \"langgraph-cli[inmem]\""
            f"{py_version_msg}"
        )

    setup_cli_logging(log_level.value.upper())

    from giga_agent.core.paths import ensure_giga_agent_dir

    ensure_giga_agent_dir()

    os.environ.setdefault("GIGA_AGENT_RUNTIME", "local")
    os.environ.setdefault("GIGA_AGENT_HOST", f"http://{str(host)}")
    os.environ.setdefault("GIGA_AGENT_PORT", str(port))
    reset_settings_cache()

    from giga_agent.core.cache import setup_cache

    setup_cache()

    # Import lazily to keep tests able to patch `giga_agent.cli.*`.
    cli = importlib.import_module("giga_agent.cli")

    logger.info(f"Loading agent from {graph_and_app_path}...")
    langgraph_runtime_config = build_langgraph_runtime_config(graph_and_app_path)
    agent = langgraph_runtime_config["agent"]
    logger.info(f"Loaded agent with {len(agent.all_modules)} modules.")

    graphs = langgraph_runtime_config["graphs"]
    auth_path = str(langgraph_runtime_config["auth_path"])
    http_config = dict(langgraph_runtime_config["http_config"])

    logger.info(f"Open: http://{host}:{port}")

    if no_reload:
        # In-process execution is enough without reload and keeps unit tests simple.
        from giga_agent.conf import GIGA_AGENT_UI

        if GIGA_AGENT_UI:
            import uvicorn

            original_uvicorn_run = uvicorn.run

            def _run_with_ui_override(*args, **kwargs):
                if args and args[0] == "langgraph_api.server:app":
                    args = ("giga_agent.scripts.combined_asgi:app", *args[1:])
                return original_uvicorn_run(*args, **kwargs)

            uvicorn.run = _run_with_ui_override
        kwargs = {}
        try:
            if "allow_blocking" in inspect.signature(run_server).parameters:
                kwargs["allow_blocking"] = True
        except Exception:
            pass

        try:
            run_server(
                host,
                port,
                False,
                graphs,
                auth={"path": auth_path},
                http=http_config,
                **kwargs,
            )
        finally:
            if GIGA_AGENT_UI:
                uvicorn.run = original_uvicorn_run
        return

    rc = _run_langgraph_server_in_subprocess(
        host=host,
        port=port,
        reload=True,
        graphs=graphs,
        auth_path=auth_path,
        http_config=http_config,
        log_level=log_level.value.upper(),
    )

    try:
        from giga_agent.core.db import dispose_engine

        dispose_coro = dispose_engine()
        try:
            cli.asyncio.run(dispose_coro)
        finally:
            try:
                if getattr(dispose_coro, "cr_frame", None) is not None:
                    dispose_coro.close()
            except Exception:
                pass
    except Exception:
        pass

    raise typer.Exit(code=rc)
