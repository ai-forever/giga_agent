from __future__ import annotations

import importlib

from ..utils.imports import _parse_import_string

LANGGRAPH_CONFIG_SCHEMA_URL = "https://langgra.ph/schema.json"
LANGGRAPH_DEFAULT_AUTH_PATH = "giga_agent.modules.auth.langgraph_auth:auth"
LANGGRAPH_DEFAULT_DEPENDENCIES = ["."]


def collect_run_server_graphs(*, agent, base_graph_target: str) -> dict[str, str]:
    # Import lazily to avoid package import cycles.
    cli = importlib.import_module("giga_agent.cli")

    graphs: dict[str, str] = {
        "giga_agent": base_graph_target,
        "giga_agent_channel": base_graph_target,
    }

    for module in agent.all_modules:
        module_subgraphs = module.get_subgraphs()
        for key, value in module_subgraphs.items():
            if key in graphs:
                raise cli.CLIException(
                    "Duplicate subgraph key "
                    f"'{key}' from module '{module.id}'. "
                    f"Key is already used by target '{graphs[key]}'."
                )
            graphs[key] = value

    return graphs


def build_langgraph_runtime_config(graph_and_app_path: str) -> dict[str, object]:
    # Import lazily to keep tests able to patch `giga_agent.cli.*`.
    cli = importlib.import_module("giga_agent.cli")

    graph, fast_api_app = cli.load_graph_and_app_from_string(graph_and_app_path)
    agent = graph.giga_agent

    path_part, graph_var, app_var = _parse_import_string(
        graph_and_app_path,
        expected_parts=3,
        format_hint=(
            "'filepath:graph_var:app_var' (e.g., giga_agent.agents.run:graph:app)"
        ),
    )

    graphs = collect_run_server_graphs(
        agent=agent,
        base_graph_target=f"{path_part}:{graph_var}",
    )

    # cors_config = {
    #     "allow_origins": [],
    #     "allow_methods": ["*"],
    #     "allow_headers": ["*"],
    #     "allow_credentials": True,
    #     "allow_origin_regex": ".*",
    #     "expose_headers": [],
    #     "max_age": 600,
    # }

    http_config: dict[str, object] = {
        # "cors": cors_config,
        "app": f"{path_part}:{app_var}",
    }

    from giga_agent.conf import GIGA_AGENT_UI

    if not GIGA_AGENT_UI:
        # When UI wrapper is disabled, let LangGraph mount itself under /api.
        http_config["mount_prefix"] = "/api/"

    return {
        "agent": agent,
        "app": fast_api_app,
        "graphs": graphs,
        "auth_path": LANGGRAPH_DEFAULT_AUTH_PATH,
        "http_config": http_config,
    }


def build_langgraph_json_config(graph_and_app_path: str) -> dict[str, object]:
    runtime_cfg = build_langgraph_runtime_config(graph_and_app_path)
    return {
        "$schema": LANGGRAPH_CONFIG_SCHEMA_URL,
        "dependencies": LANGGRAPH_DEFAULT_DEPENDENCIES,
        "graphs": runtime_cfg["graphs"],
        "auth": {"path": runtime_cfg["auth_path"]},
        "http": runtime_cfg["http_config"],
    }
