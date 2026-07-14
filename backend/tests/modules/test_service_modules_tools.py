import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.modules.integrations.vk.tools import vk_get_posts
from giga_agent.modules.weather.tools import weather


class _FakeHTTPResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ValueError("HTTP error")

    def json(self):
        return self._payload


class ServiceModulesToolsTests(unittest.IsolatedAsyncioTestCase):

    async def test_vk_tool_uses_token_from_user_secrets(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )
        user = types.SimpleNamespace(id=owner_id, secrets={"VK_TOKEN": "vk_test"})
        observed: dict[str, str] = {}

        @asynccontextmanager
        async def _session_context():
            yield object()

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, headers=None, data=None):
                observed["access_token"] = data["access_token"]
                return _FakeHTTPResponse({"response": {"items": []}})

        with patch(
            "giga_agent.modules.integrations.vk.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.integrations.vk.tools.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.integrations.vk.tools.httpx.AsyncClient",
            return_value=_FakeClient(),
        ), patch("giga_agent.modules.integrations.vk.tools.asyncio.sleep", AsyncMock()):
            assert vk_get_posts.coroutine is not None
            await vk_get_posts.coroutine(
                domain="club1",
                offset=0,
                count=1,
                runtime=runtime,
            )

        self.assertEqual(observed["access_token"], "vk_test")

    async def test_weather_tool_uses_token_from_user_secrets(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )
        user = types.SimpleNamespace(id=owner_id, secrets={"OWM_API_KEY": "owm_test"})
        observed: list[str] = []

        @asynccontextmanager
        async def _session_context():
            yield object()

        class _FakeAioHTTPResponse:
            def __init__(self, payload):
                self.status = 200
                self._payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self):
                return self._payload

        class _FakeClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def get(self, url, params=None, timeout=None):
                _ = timeout
                observed.append(params["appid"])
                if "forecast" in url:
                    return _FakeAioHTTPResponse({"city": {"name": "Moscow"}, "list": []})
                return _FakeAioHTTPResponse(
                    {
                        "name": "Moscow",
                        "weather": [],
                        "main": {},
                        "wind": {},
                        "sys": {},
                    }
                )

        with patch(
            "giga_agent.modules.weather.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.weather.tools.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.weather.tools.aiohttp.ClientSession",
            return_value=_FakeClientSession(),
        ):
            assert weather.coroutine is not None
            await weather.coroutine(city="Moscow", runtime=runtime)

        self.assertEqual(observed, ["owm_test", "owm_test"])

    async def test_tools_raise_on_missing_secret(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )
        user = types.SimpleNamespace(id=owner_id, secrets={})

        @asynccontextmanager
        async def _session_context():
            yield object()

        from giga_agent.core.integrations.errors import ReauthRequired

        async def _no_token(*_a, **_k):
            raise ReauthRequired("github")

        with patch(
            "giga_agent.modules.integrations.vk.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.integrations.vk.tools.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.core.integrations.service.get_access_token",
            _no_token,
        ):
            assert vk_get_posts.coroutine is not None
            # No integration connection and no legacy secret → guides to connect.
            with self.assertRaisesRegex(ValueError, "VK"):
                await vk_get_posts.coroutine(
                    domain="club1",
                    offset=0,
                    count=1,
                    runtime=runtime,
                )

        with patch(
            "giga_agent.modules.weather.tools.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.weather.tools.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ):
            assert weather.coroutine is not None
            with self.assertRaisesRegex(ValueError, "OWM_API_KEY"):
                await weather.coroutine(city="Moscow", runtime=runtime)
