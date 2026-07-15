"""Tests for the connector dispatch: tool sources, aggregation, meta-tools and
the inner-tool extras propagation through ToolResultMiddleware."""

import json
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

import giga_agent.core.agent.connectors.tools as ctools
from giga_agent.core.agent.connectors import (
    connector_call_tool,
    connector_get_info,
)
from giga_agent.core.agent.connectors.sources import (
    ModuleToolSource,
    collect_sources,
    match_source,
)
from giga_agent.core.module import BaseModule
from giga_agent.middlewares.tool_result import (
    _should_compress,
    _should_skip_process,
    process_tool_result,
)


@tool
def echo(x: int) -> dict:
    """Echo x back.

    Args:
        x: a number
    """
    return {"x": x}


@tool
def boom() -> ToolMessage:
    """Always errors."""
    return ToolMessage(
        content="bad",
        tool_call_id="inner",
        status="error",
        additional_kwargs={"tool_attachments": [{"file_type": "image", "path": "/x"}]},
    )


@tool(extras={"not_compress": True})
def big() -> dict:
    """Returns a chunky payload."""
    return {"data": "x" * 100}


def _runtime():
    return types.SimpleNamespace(
        config={"configurable": {"user_id": str(uuid.uuid4())}},
        tool_call_id="call-1",
        agent=object(),
    )


class DemoModule(BaseModule):
    id: str = "demo"
    label: str = "Demo"
    lazy_tools: bool = True

    async def _get_tools(self, user, agent, *, config=None, **kwargs):
        return [echo]


class ModuleToolSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_tools_builds_spec_from_schema(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        specs = await src.list_tools(user_id=uuid.uuid4())
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.name, "echo")
        self.assertEqual(spec.required, ["x"])
        self.assertEqual(json.loads(spec.params_example), {"x": 1})

    async def test_call_tool_normalizes_raw_value(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        outcome = await src.call_tool(
            "echo", {"x": 7}, _runtime(), user_id=uuid.uuid4()
        )
        self.assertFalse(outcome.is_error)
        self.assertEqual(outcome.content, {"x": 7})
        self.assertEqual(outcome.inner_name, "echo")
        self.assertEqual(outcome.inner_extras, {})

    async def test_call_tool_normalizes_error_tool_message(self):
        src = ModuleToolSource("demo", "Demo", None, [boom])
        outcome = await src.call_tool("boom", {}, _runtime(), user_id=uuid.uuid4())
        self.assertTrue(outcome.is_error)
        self.assertEqual(outcome.content, "bad")
        self.assertEqual(outcome.attachments, [{"file_type": "image", "path": "/x"}])
        self.assertEqual(outcome.inner_name, "boom")

    async def test_call_tool_carries_inner_extras(self):
        src = ModuleToolSource("demo", "Demo", None, [big])
        outcome = await src.call_tool("big", {}, _runtime(), user_id=uuid.uuid4())
        self.assertEqual(outcome.inner_extras, {"not_compress": True})

    async def test_call_tool_unknown_tool_is_error(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        outcome = await src.call_tool("nope", {}, _runtime(), user_id=uuid.uuid4())
        self.assertTrue(outcome.is_error)


class CollectSourcesTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_lazy_module_source(self):
        agent = types.SimpleNamespace(all_modules=[DemoModule()])
        user = types.SimpleNamespace(id=uuid.uuid4(), settings={})
        sources = await collect_sources(agent, user, config={})
        self.assertEqual([s.name for s in sources], ["demo"])

    async def test_respects_disabled_modules_from_config(self):
        agent = types.SimpleNamespace(all_modules=[DemoModule()])
        user = types.SimpleNamespace(id=uuid.uuid4(), settings={})
        config = {"configurable": {"disabled_modules": ["demo"]}}
        sources = await collect_sources(agent, user, config=config)
        self.assertEqual(sources, [])

    async def test_match_source_by_name_case_insensitive(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        self.assertIs(match_source([src], "DEMO"), src)
        self.assertIsNone(match_source([src], "missing"))


class ConnectorMetaToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_info_lists_tools(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        runtime = _runtime()
        ctx = (object(), types.SimpleNamespace(id=uuid.uuid4()), uuid.uuid4())
        with (
            patch.object(ctools, "_resolve_context", AsyncMock(return_value=ctx)),
            patch.object(ctools, "collect_sources", AsyncMock(return_value=[src])),
        ):
            info = await connector_get_info.coroutine(connector="demo", runtime=runtime)
        self.assertEqual(info["connector"], "demo")
        self.assertEqual([t["name"] for t in info["tools"]], ["echo"])

    async def test_call_tool_serializes_and_tags_inner(self):
        src = ModuleToolSource("demo", "Demo", None, [echo])
        runtime = _runtime()
        ctx = (object(), types.SimpleNamespace(id=uuid.uuid4()), uuid.uuid4())
        with (
            patch.object(ctools, "_resolve_context", AsyncMock(return_value=ctx)),
            patch.object(ctools, "collect_sources", AsyncMock(return_value=[src])),
        ):
            msg = await connector_call_tool.coroutine(
                connector="demo", tool="echo", runtime=runtime, params='{"x": 7}'
            )
        self.assertIsInstance(msg, ToolMessage)
        self.assertEqual(json.loads(msg.content), {"x": 7})
        self.assertEqual(msg.additional_kwargs["tool_name"], "echo")
        self.assertEqual(msg.additional_kwargs["tool_args"], {"x": 7})
        self.assertEqual(msg.additional_kwargs["effective_extras"], {})

    async def test_call_tool_unknown_connector_errors(self):
        runtime = _runtime()
        ctx = (object(), types.SimpleNamespace(id=uuid.uuid4()), uuid.uuid4())
        with (
            patch.object(ctools, "_resolve_context", AsyncMock(return_value=ctx)),
            patch.object(ctools, "collect_sources", AsyncMock(return_value=[])),
        ):
            msg = await connector_call_tool.coroutine(
                connector="ghost", tool="echo", runtime=runtime
            )
        self.assertIsInstance(msg, ToolMessage)
        self.assertEqual(msg.status, "error")


class ModuleCatalogEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_provider_modules_appear(self):
        from giga_agent.core.integrations.base import (
            ConnectionStatus,
            ManualField,
            ProviderInfo,
        )
        from giga_agent.routes.agent import _module_catalog_entries

        class _FakeProvider:
            def info(self):
                return ProviderInfo(
                    key="fake",
                    label="Fake",
                    icon="http://icon",
                    auth_kind="manual_token",
                    manual_fields=[ManualField(key="token", label="Token")],
                )

            async def status(self, *, user_id):
                return ConnectionStatus(status="connected")

        class ProviderModule(BaseModule):
            id: str = "fake"
            label: str = "Fake"
            description: str = "desc"

            def get_providers(self, **kwargs):
                return [_FakeProvider()]

        agent = types.SimpleNamespace(
            all_modules=[ProviderModule(), DemoModule()]  # DemoModule: no providers
        )
        user = types.SimpleNamespace(id=uuid.uuid4(), settings={})
        entries = await _module_catalog_entries(agent, user)
        self.assertEqual([e.module_id for e in entries], ["fake"])
        entry = entries[0]
        self.assertEqual(entry.provider_key, "fake")
        self.assertEqual(entry.auth_kind, "manual_token")
        self.assertEqual([f.key for f in entry.manual_fields], ["token"])
        self.assertEqual(entry.status, "connected")
        self.assertTrue(entry.enabled)

    async def test_disabled_module_marked_not_enabled(self):
        from giga_agent.core.integrations.base import (
            ConnectionStatus,
            ProviderInfo,
        )
        from giga_agent.routes.agent import _module_catalog_entries

        class _FakeProvider:
            def info(self):
                return ProviderInfo(
                    key="fake", label="Fake", icon=None, auth_kind="oauth2"
                )

            async def status(self, *, user_id):
                return ConnectionStatus(status="not_connected")

        class ProviderModule(BaseModule):
            id: str = "fake"
            label: str = "Fake"

            def get_providers(self, **kwargs):
                return [_FakeProvider()]

        agent = types.SimpleNamespace(all_modules=[ProviderModule()])
        user = types.SimpleNamespace(
            id=uuid.uuid4(), settings={"disabledModules": ["fake"]}
        )
        entries = await _module_catalog_entries(agent, user)
        self.assertFalse(entries[0].enabled)


class ExtrasOverrideTests(unittest.IsolatedAsyncioTestCase):
    def test_should_skip_process_reads_extras(self):
        self.assertTrue(_should_skip_process({"not_process": True}))
        self.assertFalse(_should_skip_process({}))

    def test_should_compress_honors_not_compress(self):
        self.assertFalse(_should_compress({"not_compress": True}, 10_000, 1))
        self.assertTrue(_should_compress({}, 10_000, 1))

    async def test_process_tool_result_applies_overrides(self):
        action = {
            "name": "connector_call_tool",
            "id": "1",
            "args": {"connector": "demo"},
        }
        msg = await process_tool_result(
            json.dumps({"data": "x" * 5000}),
            action,
            [],
            {"configurable": {"langgraph_auth_user": {}}},  # no owner → no infra
            tool=None,
            extras_override={"not_compress": True},
            name_override="big",
            args_override={"x": 1},
        )
        self.assertEqual(msg.additional_kwargs["tool_name"], "big")
        self.assertEqual(msg.additional_kwargs["tool_args"], {"x": 1})
        # not_compress honored → payload kept raw ("data"), not summarized ("schema").
        payload = json.loads(msg.content)
        self.assertIn("data", payload)
        self.assertNotIn("schema", payload)

    async def test_process_tool_result_compresses_without_override(self):
        action = {"name": "vk_get_posts", "id": "1", "args": {}}
        with patch(
            "giga_agent.middlewares.tool_result._get_max_tool_size", return_value=1
        ):
            msg = await process_tool_result(
                json.dumps({"data": "x" * 5000}),
                action,
                [],
                {"configurable": {"langgraph_auth_user": {}}},
                tool=None,
            )
        payload = json.loads(msg.content)
        self.assertIn("schema", payload)
