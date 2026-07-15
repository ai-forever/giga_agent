import asyncio
import json
import tempfile
import unittest
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.mcp_server import (
    McpServer,
    McpServerRepository,
    normalize_settings,
)
from giga_agent.models.users import User
from giga_agent.modules.mcp.client import list_server_tools
from giga_agent.modules.mcp.errors import McpLocalBlockedError
from giga_agent.modules.mcp.resolved import resolve_db_server
from giga_agent.utils.mcp_host import is_local_url


class HostPolicyTests(unittest.TestCase):
    def test_classification(self) -> None:
        local = [
            "http://localhost:8000/mcp",
            "http://127.0.0.1/mcp",
            "http://192.168.1.5:3000",
            "http://10.1.2.3",
            "http://172.16.0.1",
            "http://100.64.0.1",
            "http://[::1]:9000",
            "http://foo.local",
        ]
        remote = [
            "https://api.example.com/mcp/",
            "https://mcp.githubcopilot.com",
            "http://8.8.8.8",
        ]
        for url in local:
            with self.subTest(url=url):
                self.assertTrue(is_local_url(url))
        for url in remote:
            with self.subTest(url=url):
                self.assertFalse(is_local_url(url))

    def test_garbage_url_is_not_local(self) -> None:
        self.assertFalse(is_local_url("not a url"))
        self.assertFalse(is_local_url(""))


class NormalizeSettingsTests(unittest.TestCase):
    def test_bearer_keeps_known_and_drops_empty(self) -> None:
        out = normalize_settings("bearer", {"token": "abc", "extra": "x"})
        self.assertEqual(out["token"], "abc")
        self.assertEqual(out["header_name"], "Authorization")
        self.assertEqual(out["scheme"], "Bearer")
        self.assertNotIn("extra", out)

    def test_bearer_without_token_drops_token(self) -> None:
        out = normalize_settings("bearer", {})
        self.assertNotIn("token", out)

    def test_oauth_keeps_known(self) -> None:
        out = normalize_settings(
            "oauth2",
            {"scope": "read", "client_id": "c", "client_secret": "s", "junk": 1},
        )
        self.assertEqual(out, {"scope": "read", "client_id": "c", "client_secret": "s"})

    def test_none_drops_everything(self) -> None:
        self.assertEqual(normalize_settings("none", {"token": "x"}), {})


class McpServerRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(email=email, hashed_password="h", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_create_computes_is_local_and_strips_secrets(self) -> None:
        user = await self._user("a@e.io")
        async with self.session_factory() as session:
            repo = McpServerRepository(session)
            server = await repo.create(
                owner_id=user.id,
                url="http://localhost:9000/mcp",
                auth_type="bearer",
                name="local-srv",
                settings={"token": "supersecret-1234"},
            )
            self.assertTrue(server.is_local)

            resp = McpServerRepository.to_response(server, can_edit=True)
            dumped = json.dumps(resp.model_dump(mode="json"))
            self.assertTrue(resp.has_token)
            self.assertEqual(resp.token_hint, "****1234")
            self.assertNotIn("supersecret", dumped)
            self.assertNotIn("client_secret", dumped)

    async def test_update_recomputes_is_local(self) -> None:
        user = await self._user("b@e.io")
        async with self.session_factory() as session:
            repo = McpServerRepository(session)
            server = await repo.create(
                owner_id=user.id, url="https://remote.example.com/mcp"
            )
            self.assertFalse(server.is_local)
            server = await repo.update(server, url="http://127.0.0.1/mcp")
            self.assertTrue(server.is_local)

    async def test_acl_owner_sees_other_does_not(self) -> None:
        owner = await self._user("owner@e.io")
        other = await self._user("other@e.io")
        async with self.session_factory() as session:
            repo = McpServerRepository(session)
            await repo.create(
                owner_id=owner.id, url="https://x.example.com/mcp", name="s"
            )

        async with self.session_factory() as session:
            repo = McpServerRepository(session)
            owner_servers = await repo.get_readable_for_user(owner.id)
            other_servers = await repo.get_readable_for_user(other.id)
        self.assertEqual(len(owner_servers), 1)
        self.assertEqual(len(other_servers), 0)


class ClientLocalGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()

    async def test_local_server_blocked_without_runtime_local(self) -> None:
        server = McpServer(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            url="http://localhost:9999/mcp",
            auth_type="none",
            settings={},
            is_active=True,
            is_local=True,
        )
        with self.assertRaises(McpLocalBlockedError):
            await list_server_tools(resolve_db_server(server), user_id=uuid.uuid4())


class DbTokenStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "tok.sqlite"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.user_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                User(
                    id=self.user_id, email="t@e.io", hashed_password="h", is_active=True
                )
            )
            server = McpServer(
                owner_id=self.user_id,
                url="https://oauth.example.com/mcp",
                auth_type="oauth2",
                settings={},
            )
            session.add(server)
            await session.commit()
            self.server_id = server.id

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self._tmp.cleanup()

    async def test_client_info_and_token_roundtrip(self) -> None:
        from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

        from giga_agent.models.oauth_connection import mcp_provider_key
        from giga_agent.core.integrations.token_storage import DbTokenStorage

        async def _factory():
            return self.session_factory

        with mock.patch(
            "giga_agent.core.integrations.token_storage.get_session_factory",
            _factory,
        ):
            storage = DbTokenStorage(
                user_id=self.user_id,
                provider_key=mcp_provider_key(self.server_id),
                redirect_uri="https://app.example.com/cb",
            )
            self.assertIsNone(await storage.get_tokens())
            self.assertIsNone(await storage.get_client_info())

            # DCR client creds first (no access token yet -> nullable column).
            await storage.set_client_info(
                OAuthClientInformationFull(
                    client_id="cid",
                    client_secret="csecret",
                    redirect_uris=["https://app.example.com/cb"],
                )
            )
            ci = await storage.get_client_info()
            self.assertIsNotNone(ci)
            self.assertEqual(ci.client_id, "cid")

            await storage.set_tokens(
                OAuthToken(
                    access_token="acc",
                    refresh_token="ref",
                    expires_in=3600,
                    scope="read",
                )
            )
            tok = await storage.get_tokens()
            self.assertEqual(tok.access_token, "acc")
            self.assertEqual(tok.refresh_token, "ref")
            self.assertTrue(0 < (tok.expires_in or 0) <= 3600)
            # client creds preserved across the token upsert
            self.assertEqual((await storage.get_client_info()).client_id, "cid")


class LocalConfigTests(unittest.TestCase):
    def _load_with(self, payload: dict) -> dict:
        from giga_agent.modules.mcp import local_config

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mcp.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch.object(local_config, "is_local_runtime", return_value=True),
                mock.patch.object(local_config, "local_config_path", return_value=path),
            ):
                return local_config.load_local_servers()

    def test_parses_stdio_and_http_with_prefix(self) -> None:
        servers = self._load_with(
            {
                "mcpServers": {
                    "filesystem": {"command": "npx", "args": ["-y", "x"]},
                    "remote": {"url": "https://mcp.example.com/mcp"},
                }
            }
        )
        self.assertEqual(set(servers), {"local_filesystem", "local_remote"})
        fs = servers["local_filesystem"]
        self.assertEqual(fs.transport, "stdio")
        self.assertTrue(fs.is_local)
        self.assertEqual(fs.command, "npx")
        self.assertEqual(fs.cache_id, "local:filesystem")
        rem = servers["local_remote"]
        self.assertEqual(rem.transport, "http")
        self.assertFalse(rem.is_local)

    def test_empty_when_not_local_runtime(self) -> None:
        from giga_agent.modules.mcp import local_config

        with mock.patch.object(local_config, "is_local_runtime", return_value=False):
            self.assertEqual(local_config.load_local_servers(), {})


class McpAppsUiTests(unittest.TestCase):
    """MCP Apps (interactive widget) metadata plumbing."""

    class _FakeTool:
        def __init__(self, name, meta=None, annotations=None):
            self.name = name
            self.description = "d"
            self.inputSchema = {"type": "object", "properties": {}}
            self.meta = meta
            self.annotations = annotations

    def test_serialize_preserves_ui_meta(self) -> None:
        from giga_agent.modules.mcp.client import _serialize_tool

        tool = self._FakeTool(
            "create_view", meta={"ui": {"resourceUri": "ui://x/app.html"}}
        )
        out = _serialize_tool(tool)
        self.assertEqual(out["meta"], {"ui": {"resourceUri": "ui://x/app.html"}})

    def test_serialize_omits_empty_meta(self) -> None:
        from giga_agent.modules.mcp.client import _serialize_tool

        out = _serialize_tool(self._FakeTool("read_me", meta=None))
        self.assertNotIn("meta", out)

    def test_resource_uri_nested_and_flat(self) -> None:
        from giga_agent.modules.mcp.tools import _ui_resource_uri

        self.assertEqual(
            _ui_resource_uri({"meta": {"ui": {"resourceUri": "ui://a"}}}), "ui://a"
        )
        self.assertEqual(
            _ui_resource_uri({"meta": {"ui/resourceUri": "ui://b"}}), "ui://b"
        )
        self.assertIsNone(_ui_resource_uri({"meta": {"ui": {}}}))
        self.assertIsNone(_ui_resource_uri({}))

    def test_visibility_hides_app_only_tools(self) -> None:
        from giga_agent.modules.mcp.tools import _visible_to_model

        # No meta / no visibility → visible to the model.
        self.assertTrue(_visible_to_model({}))
        self.assertTrue(_visible_to_model({"meta": {"ui": {}}}))
        self.assertTrue(
            _visible_to_model({"meta": {"ui": {"visibility": ["model", "app"]}}})
        )
        # App-only → hidden from the LLM.
        self.assertFalse(_visible_to_model({"meta": {"ui": {"visibility": ["app"]}}}))

    def test_app_gate(self) -> None:
        from giga_agent.modules.mcp.tools import _callable_by_app

        # Unset visibility defaults to app-callable.
        self.assertTrue(_callable_by_app({}))
        self.assertTrue(_callable_by_app({"meta": {"ui": {"visibility": ["app"]}}}))
        self.assertTrue(
            _callable_by_app({"meta": {"ui": {"visibility": ["model", "app"]}}})
        )
        # Model-only tools must not be reachable from the widget bridge.
        self.assertFalse(_callable_by_app({"meta": {"ui": {"visibility": ["model"]}}}))


class UiResourceServerRefTests(unittest.IsolatedAsyncioTestCase):
    """A local server's mcp_ui attachment carries cache_id ('local:<ns>'), which
    must resolve even though load_local_servers() is keyed by name."""

    class _FakeRepo:
        async def get_readable_for_user(self, _user_id):
            return []

    async def test_local_resolves_by_name_and_cache_id(self) -> None:
        from giga_agent.modules.mcp.api import servers as servers_api
        from giga_agent.modules.mcp.resolved import ResolvedServer

        local = ResolvedServer(
            name="local_map",
            transport="stdio",
            is_local=True,
            cache_id="local:map",
            source="file",
            command="npx",
        )
        with mock.patch.object(
            servers_api, "load_local_servers", return_value={"local_map": local}
        ):
            for ref in ("local:map", "local_map"):
                with self.subTest(ref=ref):
                    resolved = await servers_api._resolve_readable_server_ref(
                        ref, user_id=uuid.uuid4(), repo=self._FakeRepo()
                    )
                    self.assertIs(resolved, local)

            from fastapi import HTTPException

            with self.assertRaises(HTTPException):
                await servers_api._resolve_readable_server_ref(
                    "local:nope", user_id=uuid.uuid4(), repo=self._FakeRepo()
                )


class CallServerToolTests(unittest.IsolatedAsyncioTestCase):
    """A tool call surfaces timeouts as McpTimeoutError and passes others through."""

    class _Part:
        def __init__(self, text):
            self._t = text

        def model_dump(self, **_kwargs):
            return {"type": "text", "text": self._t}

    class _Result:
        def __init__(self, text="ok", structured=None):
            self.content = [CallServerToolTests._Part(text)]
            self.structuredContent = structured
            self.isError = False

    @staticmethod
    def _server():
        from giga_agent.modules.mcp.resolved import ResolvedServer

        return ResolvedServer(
            name="Excalidraw",
            transport="http",
            is_local=False,
            cache_id="c",
            source="db",
            url="https://mcp.excalidraw.com/mcp",
        )

    def tearDown(self) -> None:
        from giga_agent.modules.mcp import pool

        pool.reset_pool()

    def _patch(self, call_mock):
        from giga_agent.modules.mcp import pool

        # Drive the direct (one-shot) path; _open_session is looked up in `pool`.
        pool._pool = pool.DirectPool()

        @asynccontextmanager
        async def fake_open(*_a, **_k):
            sess = mock.Mock()
            sess.call_tool = call_mock
            yield sess

        return mock.patch.object(pool, "_open_session", fake_open)

    async def test_succeeds(self) -> None:
        from giga_agent.modules.mcp import client

        result = self._Result("https://exc/x", {"checkpointId": "c"})
        call = mock.AsyncMock(return_value=result)
        with self._patch(call):
            parts, is_error, structured = await client.call_server_tool(
                self._server(),
                "export",
                {},
                user_id=uuid.uuid4(),
            )
        self.assertEqual(call.await_count, 1)
        self.assertFalse(is_error)
        self.assertEqual(parts[0]["text"], "https://exc/x")
        self.assertEqual(structured, {"checkpointId": "c"})

    async def test_timeout_raises(self) -> None:
        from giga_agent.modules.mcp import client
        from giga_agent.modules.mcp.errors import McpTimeoutError

        call = mock.AsyncMock(side_effect=asyncio.TimeoutError())
        with self._patch(call), self.assertRaises(McpTimeoutError):
            await client.call_server_tool(
                self._server(),
                "export",
                {},
                user_id=uuid.uuid4(),
            )
        self.assertEqual(call.await_count, 1)

    async def test_non_timeout_passthrough(self) -> None:
        from giga_agent.modules.mcp import client
        from giga_agent.modules.mcp.errors import McpToolError

        call = mock.AsyncMock(side_effect=McpToolError("boom"))
        with self._patch(call), self.assertRaises(McpToolError):
            await client.call_server_tool(
                self._server(),
                "x",
                {},
                user_id=uuid.uuid4(),
            )
        self.assertEqual(call.await_count, 1)


if __name__ == "__main__":
    unittest.main()
