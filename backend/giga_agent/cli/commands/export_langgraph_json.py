from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from giga_agent.core.logging import get_logger, setup_cli_logging

from ._langgraph_config import build_langgraph_json_config

logger = get_logger(__name__)


def export_langgraph_json(
    graph_and_app_path: Annotated[
        str,
        typer.Argument(
            help=("Path to graph and app, e.g. giga_agent.agents.run:graph:app")
        ),
    ] = "giga_agent.agents.run:graph:app",
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Output file path for generated langgraph.json",
        ),
    ] = "langgraph.json",
) -> None:
    """
    Export langgraph.json config using the same graph/auth/http settings as `dev`.
    """
    setup_cli_logging("INFO")

    logger.info(f"Loading agent from {graph_and_app_path}...")
    config = build_langgraph_json_config(graph_and_app_path)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    logger.info(f"Wrote LangGraph config to {output_path}")
