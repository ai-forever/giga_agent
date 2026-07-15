import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch, Mock

from langchain_core.messages import AIMessage, HumanMessage

from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.middlewares.thread_title import ThreadTitleMiddleware


class ThreadTitleMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_if_thread_title_already_set(self):
        middleware = ThreadTitleMiddleware()
        state = {"messages": [HumanMessage(content="Сделай план проекта")]}
        config = {
            "configurable": {
                "thread_id": "t-1",
                "langgraph_auth_user": {"identity": str(uuid.uuid4())},
            },
        }

        update = AsyncMock()
        with (
            patch(
                "giga_agent.middlewares.thread_title.get_thread_metadata",
                AsyncMock(return_value={"thread_title": "Уже есть"}),
            ),
            patch(
                "giga_agent.middlewares.thread_title.update_thread_metadata",
                update,
            ),
        ):
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        update.assert_not_awaited()

    async def test_generates_and_saves_title_once(self):
        middleware = ThreadTitleMiddleware()
        user_id = uuid.uuid4()
        fast_llm_id = uuid.uuid4()
        fallback_llm_id = uuid.uuid4()

        user = types.SimpleNamespace(
            id=user_id,
            fast_llm_id=fast_llm_id,
            llm_id=fallback_llm_id,
        )

        state = {
            "messages": [HumanMessage(content="Помоги выбрать ноутбук для работы")]
        }
        config = {
            "configurable": {
                "thread_id": "t-2",
                "langgraph_auth_user": {"identity": str(user_id)},
                "runtime_resolver": RuntimeResolver(user),
            }
        }

        llm = types.SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=AIMessage(content='{"thread_title":"Выбор ноутбука"}')
            )
        )
        llm.with_config = Mock(return_value=llm)
        llm_runtime = types.SimpleNamespace(get_llm=AsyncMock(return_value=llm))

        update = AsyncMock()
        with (
            patch(
                "giga_agent.middlewares.thread_title.get_thread_metadata",
                AsyncMock(return_value={}),
            ),
            patch(
                "giga_agent.middlewares.thread_title.update_thread_metadata",
                update,
            ),
            patch.object(
                RuntimeResolver,
                "get_fast_llm_runtime",
                AsyncMock(return_value=llm_runtime),
            ),
        ):
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        update.assert_awaited_once()
        args, kwargs = update.await_args
        self.assertEqual(args[1], "t-2")
        self.assertEqual(args[2]["thread_title"], "Выбор ноутбука")

    async def test_fallback_to_first_three_words_when_llm_not_json(self):
        middleware = ThreadTitleMiddleware()
        user_id = uuid.uuid4()
        llm_id = uuid.uuid4()

        user = types.SimpleNamespace(
            id=user_id,
            fast_llm_id=None,
            llm_id=llm_id,
        )

        state = {
            "messages": [HumanMessage(content="Помоги выбрать ноутбук для работы")]
        }
        config = {
            "configurable": {
                "thread_id": "t-3",
                "langgraph_auth_user": {"identity": str(user_id)},
                "runtime_resolver": RuntimeResolver(user),
            }
        }

        llm = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content="Выбор ноутбука"))
        )
        llm.with_config = Mock(return_value=llm)
        llm_runtime = types.SimpleNamespace(get_llm=AsyncMock(return_value=llm))

        update = AsyncMock()
        with (
            patch(
                "giga_agent.middlewares.thread_title.get_thread_metadata",
                AsyncMock(return_value={}),
            ),
            patch(
                "giga_agent.middlewares.thread_title.update_thread_metadata",
                update,
            ),
            patch.object(
                RuntimeResolver,
                "get_fast_llm_runtime",
                AsyncMock(return_value=llm_runtime),
            ),
        ):
            await middleware.before_agent(state, runtime=AsyncMock(), config=config)

        update.assert_awaited_once()
        args, kwargs = update.await_args
        self.assertEqual(args[1], "t-3")
        self.assertEqual(args[2]["thread_title"], "Помоги выбрать ноутбук")
