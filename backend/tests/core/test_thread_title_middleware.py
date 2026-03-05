import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch, Mock

from langchain_core.messages import AIMessage, HumanMessage

from giga_agent.middlewares.thread_title import ThreadTitleMiddleware


class ThreadTitleMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_if_thread_title_already_set(self):
        middleware = ThreadTitleMiddleware()
        state = {"messages": [HumanMessage(content="Сделай план проекта")]}
        config = {
            "metadata": {"thread_title": "Уже есть"},
            "configurable": {
                "thread_id": "t-1",
                "langgraph_auth_user": {"identity": str(uuid.uuid4())},
            },
        }

        client = types.SimpleNamespace(
            threads=types.SimpleNamespace(
                get=AsyncMock(return_value={"metadata": {"thread_title": "Уже есть"}}),
                update=AsyncMock(),
            )
        )

        with patch(
            "giga_agent.middlewares.thread_title.get_client", return_value=client
        ):
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        client.threads.update.assert_not_awaited()

    async def test_generates_and_saves_title_once(self):
        middleware = ThreadTitleMiddleware()
        user_id = uuid.uuid4()
        fast_llm_id = uuid.uuid4()
        fallback_llm_id = uuid.uuid4()

        state = {
            "messages": [HumanMessage(content="Помоги выбрать ноутбук для работы")]
        }
        config = {
            "configurable": {
                "thread_id": "t-2",
                "langgraph_auth_user": {"identity": str(user_id)},
            }
        }

        client = types.SimpleNamespace(
            threads=types.SimpleNamespace(
                get=AsyncMock(return_value={"metadata": {}}),
                update=AsyncMock(),
            )
        )

        llm = types.SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=AIMessage(content='{"thread_title":"Выбор ноутбука"}')
            )
        )
        llm.with_config = Mock(return_value=llm)
        llm_runtime = types.SimpleNamespace(get_llm=AsyncMock(return_value=llm))

        @asynccontextmanager
        async def _session_context():
            yield object()

        user = types.SimpleNamespace(fast_llm_id=fast_llm_id, llm_id=fallback_llm_id)

        with patch(
            "giga_agent.middlewares.thread_title.get_client", return_value=client
        ), patch(
            "giga_agent.middlewares.thread_title.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.middlewares.thread_title.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.middlewares.thread_title.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ) as resolve_llm:
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        resolve_llm.assert_awaited_once()
        called_llm_id = resolve_llm.await_args.args[0]
        self.assertEqual(called_llm_id, fast_llm_id)

        client.threads.update.assert_awaited_once()
        args, kwargs = client.threads.update.await_args
        self.assertEqual(args[0], "t-2")
        self.assertEqual(kwargs["metadata"]["thread_title"], "Выбор ноутбука")

    async def test_fallback_to_first_three_words_when_llm_not_json(self):
        middleware = ThreadTitleMiddleware()
        user_id = uuid.uuid4()
        llm_id = uuid.uuid4()

        state = {
            "messages": [HumanMessage(content="Помоги выбрать ноутбук для работы")]
        }
        config = {
            "configurable": {
                "thread_id": "t-3",
                "langgraph_auth_user": {"identity": str(user_id)},
            }
        }

        client = types.SimpleNamespace(
            threads=types.SimpleNamespace(
                get=AsyncMock(return_value={"metadata": {}}),
                update=AsyncMock(),
            )
        )

        llm = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content="Выбор ноутбука"))
        )
        llm.with_config = Mock(return_value=llm)
        llm_runtime = types.SimpleNamespace(get_llm=AsyncMock(return_value=llm))

        @asynccontextmanager
        async def _session_context():
            yield object()

        user = types.SimpleNamespace(fast_llm_id=None, llm_id=llm_id)

        with patch(
            "giga_agent.middlewares.thread_title.get_client", return_value=client
        ), patch(
            "giga_agent.middlewares.thread_title.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.middlewares.thread_title.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.middlewares.thread_title.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ):
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        client.threads.update.assert_awaited_once()
        args, kwargs = client.threads.update.await_args
        self.assertEqual(args[0], "t-3")
        self.assertEqual(kwargs["metadata"]["thread_title"], "Помоги выбрать ноутбук")
