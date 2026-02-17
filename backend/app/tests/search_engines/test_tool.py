import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.search_engines.tool import search


class SearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_tool_requires_runtime(self):
        assert search.coroutine is not None
        with self.assertRaises(ValueError):
            await search.coroutine(queries=["q1"], runtime=None)

    async def test_search_tool_raises_when_user_missing(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )

        with patch(
            "giga_agent.search_engines.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            assert search.coroutine is not None
            with self.assertRaises(ValueError):
                await search.coroutine(queries=["q1"], runtime=runtime)

    async def test_search_tool_raises_when_engine_not_selected(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )
        user = types.SimpleNamespace(id=owner_id, search_engine_id=None)

        with patch(
            "giga_agent.search_engines.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ):
            assert search.coroutine is not None
            with self.assertRaises(ValueError):
                await search.coroutine(queries=["q1"], runtime=runtime)

    async def test_search_tool_returns_manager_result(self):
        owner_id = uuid.uuid4()
        runtime = types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )
        user = types.SimpleNamespace(id=owner_id, search_engine_id=uuid.uuid4())
        engine = types.SimpleNamespace(
            search=AsyncMock(return_value=[{"query": "q1", "result": {"ok": True}}])
        )

        with patch(
            "giga_agent.search_engines.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.search_engines.tool.SearchEngineManager.resolve_by_id",
            AsyncMock(return_value=engine),
        ) as mocked_resolve:
            assert search.coroutine is not None
            result = await search.coroutine(queries=["q1"], runtime=runtime)

        mocked_resolve.assert_awaited_once_with(user.search_engine_id)
        self.assertEqual(result, [{"query": "q1", "result": {"ok": True}}])
