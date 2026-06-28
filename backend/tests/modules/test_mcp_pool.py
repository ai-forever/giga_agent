"""Behavioral tests for the embedded MCP session pool (giga_agent.modules.mcp.pool).

These exercise the actor/worker mechanics with a fake ``_open_session`` so we can
count handshakes (= how many times a session is actually opened) and assert reuse
/ eviction / poisoning without a real MCP server.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import mock

from giga_agent.core.cache import setup_cache
from giga_agent.modules.mcp import pool as poolmod
from giga_agent.modules.mcp.resolved import ResolvedServer


def _server(cache_id: str = "srv") -> ResolvedServer:
    return ResolvedServer(
        name="Fake",
        transport="http",
        is_local=False,
        cache_id=cache_id,
        source="db",
        url="https://example.com/mcp",
    )


class _Part:
    def __init__(self, text: str):
        self._t = text

    def model_dump(self, **_kwargs):
        return {"type": "text", "text": self._t}


class _FakeSession:
    """A stand-in ClientSession; behavior is driven by the enclosing factory."""

    def __init__(self, *, call_behavior=None):
        self._call_behavior = call_behavior

    async def list_tools(self):
        tool = SimpleNamespace(
            name="t", description="d", inputSchema={}, meta=None, annotations=None
        )
        return SimpleNamespace(tools=[tool])

    async def call_tool(self, name, args):
        if self._call_behavior is not None:
            await self._call_behavior(name, args)
        return SimpleNamespace(
            content=[_Part(f"ok-{name}")], structuredContent=None, isError=False
        )

    async def read_resource(self, uri):
        return SimpleNamespace(
            contents=[SimpleNamespace(text="<html>", mimeType="text/html")]
        )


def _fake_open_factory(counters, *, call_behavior=None):
    @asynccontextmanager
    async def fake_open(server, *, user_id=None, db=None, throttle=True):
        counters["opened"] += 1
        counters["active"] += 1
        try:
            yield _FakeSession(call_behavior=call_behavior)
        finally:
            counters["active"] -= 1

    return fake_open


class PoolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        setup_cache()
        poolmod.reset_pool()

    async def asyncTearDown(self) -> None:
        poolmod.reset_pool()

    def _pool(self, **over):
        cfg = dict(
            max_per_server=4,
            max_per_user=8,
            max_total=200,
            idle_ttl=300,
            max_lifetime=1800,
        )
        cfg.update(over)
        return poolmod.LocalSessionPool(**cfg)

    async def test_warm_session_reused_across_acquires(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool()
        uid = uuid.uuid4()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_server(), user_id=uid) as h1:
                await h1.call_tool("a", {})
            async with pool.acquire(_server(), user_id=uid) as h2:
                await h2.call_tool("b", {})
            self.assertEqual(counters["opened"], 1)  # one warm session, reused
            await pool.shutdown()
        self.assertEqual(counters["active"], 0)

    async def test_list_and_call_share_one_session(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_server("affinity"), user_id=uuid.uuid4()) as h:
                await h.list_tools()
                await h.call_tool("a", {})
            self.assertEqual(counters["opened"], 1)  # gate + call → same handshake
            await pool.shutdown()

    async def test_at_capacity_falls_back_to_direct(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool(max_per_server=1)
        uid = uuid.uuid4()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_server(), user_id=uid) as h1:
                # h1 holds the single warm slot (busy) → h2 must open a one-shot.
                async with pool.acquire(_server(), user_id=uid) as h2:
                    await h2.call_tool("x", {})
                await h1.call_tool("y", {})
            self.assertEqual(counters["opened"], 2)
            await pool.shutdown()

    async def test_broken_session_is_poisoned_not_reused(self) -> None:
        counters = {"opened": 0, "active": 0}
        boom = {"armed": True}

        async def behavior(name, args):
            if boom["armed"]:
                boom["armed"] = False
                raise RuntimeError("protocol error")

        pool = self._pool()
        uid = uuid.uuid4()
        fake = _fake_open_factory(counters, call_behavior=behavior)
        with mock.patch.object(poolmod, "_open_session", fake):
            with self.assertRaises(RuntimeError):
                async with pool.acquire(_server(), user_id=uid) as h:
                    await h.call_tool("a", {})
            # The poisoned worker was dropped; the next acquire opens a fresh one.
            async with pool.acquire(_server(), user_id=uid) as h2:
                await h2.call_tool("b", {})
            self.assertEqual(counters["opened"], 2)
            await pool.shutdown()

    async def test_idle_session_evicted_after_ttl(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool(idle_ttl=1)
        uid = uuid.uuid4()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_server(), user_id=uid) as h:
                await h.call_tool("a", {})
            self.assertEqual(counters["active"], 1)  # warm, parked
            await asyncio.sleep(1.4)
            self.assertEqual(counters["active"], 0)  # idle TTL closed it
            # A new acquire must open a fresh session.
            async with pool.acquire(_server(), user_id=uid) as h2:
                await h2.call_tool("b", {})
            self.assertEqual(counters["opened"], 2)
            await pool.shutdown()

    async def test_changed_config_recycles_warm_worker(self) -> None:
        # Same cache_id (same mcp.json namespace) but a changed config_sig — i.e.
        # the entry's command/env was edited — must NOT reuse the stale subprocess.
        counters = {"opened": 0, "active": 0}
        pool = self._pool()
        uid = uuid.uuid4()

        def _local(sig: str) -> ResolvedServer:
            return ResolvedServer(
                name="local_fs",
                transport="stdio",
                is_local=True,
                cache_id="local:fs",
                source="file",
                config_sig=sig,
                command="npx",
            )

        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_local("v1"), user_id=uid) as h1:
                await h1.call_tool("a", {})
            # Config edited → fingerprint changed → old warm worker is retired,
            # a fresh session is opened for the new config.
            async with pool.acquire(_local("v2"), user_id=uid) as h2:
                await h2.call_tool("b", {})
            self.assertEqual(counters["opened"], 2)
            await pool.shutdown()
        # Let the retired worker's task finish closing its session.
        for _ in range(50):
            if counters["active"] == 0:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(counters["active"], 0)

    async def test_shutdown_closes_warm_sessions(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(_server(), user_id=uuid.uuid4()) as h:
                await h.call_tool("a", {})
            self.assertEqual(counters["active"], 1)
            await pool.shutdown()
            self.assertEqual(counters["active"], 0)

    async def test_oauth_server_bypasses_pool(self) -> None:
        counters = {"opened": 0, "active": 0}
        pool = self._pool()
        oauth = ResolvedServer(
            name="OA",
            transport="http",
            is_local=False,
            cache_id="oa",
            source="db",
            url="https://example.com/mcp",
            auth_type="oauth2",
        )
        uid = uuid.uuid4()
        with mock.patch.object(poolmod, "_open_session", _fake_open_factory(counters)):
            async with pool.acquire(oauth, user_id=uid) as h1:
                await h1.call_tool("a", {})
            async with pool.acquire(oauth, user_id=uid) as h2:
                await h2.call_tool("b", {})
            # OAuth is one-shot for now → no reuse → two handshakes.
            self.assertEqual(counters["opened"], 2)
            self.assertEqual(counters["active"], 0)


if __name__ == "__main__":
    unittest.main()
