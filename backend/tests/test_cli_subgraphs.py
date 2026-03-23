import sys
import types
import unittest
import asyncio
from urllib.parse import quote
from unittest.mock import patch

from fastapi import FastAPI

from giga_agent.cli import CLIException, dev
from giga_agent.core.module import BaseModule


class _SubgraphModule(BaseModule):
    id: str = "subgraph_module"
    subgraphs: dict[str, str] = {}

    def get_subgraphs(self) -> dict[str, str]:
        return self.subgraphs


class CLISubgraphsTests(unittest.TestCase):
    def _make_agent_graph(self, modules: list[BaseModule]):
        agent = types.SimpleNamespace(all_modules=modules)
        graph = types.SimpleNamespace(giga_agent=agent)
        return graph

    def _make_langgraph_api_modules(self, run_server):
        langgraph_api_pkg = types.ModuleType("langgraph_api")
        langgraph_api_cli = types.ModuleType("langgraph_api.cli")
        langgraph_api_cli.run_server = run_server
        return {
            "langgraph_api": langgraph_api_pkg,
            "langgraph_api.cli": langgraph_api_cli,
        }

    def test_dev_passes_merged_graphs_to_run_server(self):
        captured = {}

        def _run_server(host, port, reload, graphs, auth=None, http=None, **kwargs):
            captured["host"] = host
            captured["port"] = port
            captured["reload"] = reload
            captured["graphs"] = graphs
            captured["auth"] = auth
            captured["http"] = http
            captured["kwargs"] = kwargs

        graph = self._make_agent_graph(
            modules=[
                _SubgraphModule(
                    subgraphs={
                        "landing": "giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph"
                    }
                )
            ]
        )

        with patch.dict(
            sys.modules, self._make_langgraph_api_modules(_run_server)
        ), patch(
            "giga_agent.cli.load_graph_and_app_from_string",
            return_value=(graph, FastAPI()),
        ), patch(
            "giga_agent.cli.apply_migrations"
        ) as apply_migrations, patch(
            "giga_agent.cli.asyncio.run"
        ), patch(
            "giga_agent.core.cache.setup_cache"
        ):
            dev(
                graph_and_app_path="giga_agent.agents.run:graph:app",
                no_reload=True,
            )
        apply_migrations.assert_not_called()

        self.assertEqual(
            captured["graphs"],
            {
                "giga_agent": "giga_agent.agents.run:graph",
                "landing": "giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph",
            },
        )
        self.assertEqual(
            captured["http"],
            {
                "app": "giga_agent.agents.run:app",
            },
        )
        self.assertEqual(captured["kwargs"]["timeout_graceful_shutdown"], 3)

    def test_dev_uses_default_graph_and_app_path(self):
        graph = self._make_agent_graph(modules=[])

        with patch.dict(
            sys.modules, self._make_langgraph_api_modules(lambda *args, **kwargs: None)
        ), patch(
            "giga_agent.cli.load_graph_and_app_from_string",
            return_value=(graph, FastAPI()),
        ) as load_graph_and_app, patch(
            "giga_agent.cli.apply_migrations"
        ) as apply_migrations, patch(
            "giga_agent.cli.asyncio.run"
        ), patch(
            "giga_agent.core.cache.setup_cache"
        ):
            dev(no_reload=True)

        load_graph_and_app.assert_called_once_with("giga_agent.agents.run:graph:app")
        apply_migrations.assert_not_called()

    def test_dev_fails_on_duplicate_subgraph_key(self):
        def _run_server(*args, **kwargs):
            self.fail("run_server should not be called on duplicate subgraph keys")

        graph = self._make_agent_graph(
            modules=[
                _SubgraphModule(subgraphs={"landing": "module.one:graph"}),
                _SubgraphModule(subgraphs={"landing": "module.two:graph"}),
            ]
        )

        with patch.dict(
            sys.modules, self._make_langgraph_api_modules(_run_server)
        ), patch(
            "giga_agent.cli.load_graph_and_app_from_string",
            return_value=(graph, FastAPI()),
        ), patch(
            "giga_agent.cli.apply_migrations"
        ) as apply_migrations, patch(
            "giga_agent.cli.asyncio.run"
        ), patch(
            "giga_agent.core.cache.setup_cache"
        ):
            with self.assertRaises(CLIException) as exc:
                dev(
                    graph_and_app_path="giga_agent.agents.run:graph:app",
                    no_reload=True,
                )

        self.assertIn("Duplicate subgraph key 'landing'", str(exc.exception))
        apply_migrations.assert_not_called()

    def test_dev_no_reload_disposes_engine_after_run_server_returns(self):
        graph = self._make_agent_graph(modules=[])
        dispose_coro = object()

        with patch.dict(
            sys.modules, self._make_langgraph_api_modules(lambda *args, **kwargs: None)
        ), patch(
            "giga_agent.cli.load_graph_and_app_from_string",
            return_value=(graph, FastAPI()),
        ), patch(
            "giga_agent.cli.apply_migrations"
        ), patch(
            "giga_agent.core.cache.setup_cache"
        ), patch(
            "giga_agent.core.db.dispose_engine",
            return_value=dispose_coro,
        ) as dispose_engine, patch(
            "giga_agent.cli.asyncio.run"
        ) as asyncio_run:
            dev(no_reload=True)

        dispose_engine.assert_called_once_with()
        asyncio_run.assert_called_once()
        self.assertTrue(asyncio.iscoroutine(asyncio_run.call_args.args[0]))
