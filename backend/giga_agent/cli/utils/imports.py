from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from types import ModuleType
from typing import Tuple

import typer
from fastapi import FastAPI
from langgraph.graph.state import CompiledStateGraph

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState, Context


def _parse_import_string(
    import_string: str, expected_parts: int, format_hint: str
) -> tuple[str, ...]:
    parts = import_string.split(":")
    if len(parts) != expected_parts:
        raise typer.BadParameter(f"Format must be {format_hint}")
    return tuple(parts)


def _ensure_cwd_in_sys_path() -> None:
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


def _load_module_from_path(path_part: str, module_alias: str) -> ModuleType:
    _ensure_cwd_in_sys_path()

    if os.path.exists(path_part) or os.path.exists(path_part + ".py"):
        filename = path_part if path_part.endswith(".py") else path_part + ".py"
        spec = importlib.util.spec_from_file_location(module_alias, filename)
        if spec is None or spec.loader is None:
            raise typer.BadParameter(f"Could not load file: {filename}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    try:
        return importlib.import_module(path_part)
    except ImportError as e:
        raise typer.BadParameter(f"Could not import module/file '{path_part}': {e}")


def _get_module_attr(module: ModuleType, attr_name: str, path_part: str):
    value = getattr(module, attr_name, None)
    if value is None:
        raise typer.BadParameter(f"Variable '{attr_name}' not found in '{path_part}'")
    return value


def load_agent_from_string(import_string: str) -> BaseAgent:
    """
    Parses 'my_script.py:my_agent' or 'module.submodule:agent_var'
    and returns an agent instance.
    """
    path_part, var_name = _parse_import_string(
        import_string,
        expected_parts=2,
        format_hint=("'filepath:variable_name' (e.g., giga_agent.agents.run:agent)"),
    )

    module = _load_module_from_path(path_part, "user_agent_config")
    agent_instance = _get_module_attr(module, var_name, path_part)

    if not isinstance(agent_instance, BaseAgent):
        raise typer.BadParameter(
            f"Variable '{var_name}' is not an instance of giga_agent.Agent"
        )

    return agent_instance


def load_graph_and_app_from_string(
    import_string: str,
) -> Tuple[CompiledStateGraph[AgentState, Context], FastAPI]:
    """
    Parses 'my_script.py:graph:app' or 'module.submodule:graph:app'
    and returns (graph, FastAPI app).
    """
    path_part, graph_var, app_var = _parse_import_string(
        import_string,
        expected_parts=3,
        format_hint=(
            "'filepath:graph_var:app_var' (e.g., giga_agent.agents.run:graph:app)"
        ),
    )

    module = _load_module_from_path(path_part, "user_graph_config")
    graph_instance = _get_module_attr(module, graph_var, path_part)
    app_instance = _get_module_attr(module, app_var, path_part)

    if not isinstance(graph_instance, CompiledStateGraph):
        raise typer.BadParameter(
            f"Variable '{graph_var}' is not a CompiledStateGraph instance"
        )

    if not isinstance(app_instance, FastAPI):
        raise typer.BadParameter(f"Variable '{app_var}' is not a FastAPI instance")

    return graph_instance, app_instance
