import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from giga_agent.modules.mem_zero_memory.memory import (
    migrate_user_memories_for_embedding_change,
)
from giga_agent.modules.mem_zero_memory.module import MemZeroModule


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class MemZeroMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrate_old_to_new_reimports_and_deletes_old(self):
        user_id = uuid.uuid4()
        old_embedding_id = uuid.uuid4()
        new_embedding_id = uuid.uuid4()
        user = types.SimpleNamespace(id=user_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        session = object()
        session_factory = Mock(return_value=_SessionContext(session))
        old_memory = types.SimpleNamespace(
            get_all=AsyncMock(
                return_value={
                    "results": [
                        {"memory": "alpha", "role": "user"},
                        {"memory": "beta"},
                    ]
                }
            ),
            delete_all=AsyncMock(return_value=None),
        )
        new_memory = types.SimpleNamespace(add=AsyncMock(return_value=None))

        async def _memory_by_embedding(*, embedding_id, **kwargs):
            if embedding_id == old_embedding_id:
                return old_memory
            if embedding_id == new_embedding_id:
                return new_memory
            raise AssertionError("unexpected embedding_id")

        with patch(
            "giga_agent.modules.mem_zero_memory.memory.get_session_factory",
            AsyncMock(return_value=session_factory),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory._get_memory_for_user_with_embedding_id",
            AsyncMock(side_effect=_memory_by_embedding),
        ):
            await migrate_user_memories_for_embedding_change(
                user_id=user_id,
                old_embedding_id=old_embedding_id,
                new_embedding_id=new_embedding_id,
            )

        new_memory.add.assert_awaited_once()
        self.assertEqual(
            new_memory.add.await_args.kwargs,
            {"user_id": str(user_id), "infer": False},
        )
        self.assertEqual(
            new_memory.add.await_args.args[0],
            [
                {"role": "user", "content": "alpha"},
                {"role": "user", "content": "beta"},
            ],
        )
        old_memory.delete_all.assert_awaited_once_with(user_id=str(user_id))

    async def test_migrate_noop_when_old_missing(self):
        with patch(
            "giga_agent.modules.mem_zero_memory.memory.get_session_factory",
            AsyncMock(),
        ) as mocked_factory:
            await migrate_user_memories_for_embedding_change(
                user_id=uuid.uuid4(),
                old_embedding_id=None,
                new_embedding_id=uuid.uuid4(),
            )
        mocked_factory.assert_not_awaited()

    async def test_migrate_delete_only_when_new_missing(self):
        user_id = uuid.uuid4()
        old_embedding_id = uuid.uuid4()
        user = types.SimpleNamespace(id=user_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        session = object()
        session_factory = Mock(return_value=_SessionContext(session))
        old_memory = types.SimpleNamespace(delete_all=AsyncMock(return_value=None))

        with patch(
            "giga_agent.modules.mem_zero_memory.memory.get_session_factory",
            AsyncMock(return_value=session_factory),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory._get_memory_for_user_with_embedding_id",
            AsyncMock(return_value=old_memory),
        ) as mocked_get_memory:
            await migrate_user_memories_for_embedding_change(
                user_id=user_id,
                old_embedding_id=old_embedding_id,
                new_embedding_id=None,
            )

        mocked_get_memory.assert_awaited_once()
        old_memory.delete_all.assert_awaited_once_with(user_id=str(user_id))

    async def test_migrate_does_not_delete_old_on_import_error(self):
        user_id = uuid.uuid4()
        old_embedding_id = uuid.uuid4()
        new_embedding_id = uuid.uuid4()
        user = types.SimpleNamespace(id=user_id, llm_id=uuid.uuid4(), fast_llm_id=None)
        session = object()
        session_factory = Mock(return_value=_SessionContext(session))
        old_memory = types.SimpleNamespace(
            get_all=AsyncMock(return_value={"results": [{"memory": "alpha"}]}),
            delete_all=AsyncMock(return_value=None),
        )
        new_memory = types.SimpleNamespace(
            add=AsyncMock(side_effect=RuntimeError("import failed"))
        )

        async def _memory_by_embedding(*, embedding_id, **kwargs):
            return old_memory if embedding_id == old_embedding_id else new_memory

        with patch(
            "giga_agent.modules.mem_zero_memory.memory.get_session_factory",
            AsyncMock(return_value=session_factory),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.mem_zero_memory.memory._get_memory_for_user_with_embedding_id",
            AsyncMock(side_effect=_memory_by_embedding),
        ):
            with self.assertRaises(RuntimeError):
                await migrate_user_memories_for_embedding_change(
                    user_id=user_id,
                    old_embedding_id=old_embedding_id,
                    new_embedding_id=new_embedding_id,
                )

        old_memory.delete_all.assert_not_awaited()


class MemZeroStartupSubscribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_startup_subscribes_only_once(self):
        module = MemZeroModule()
        with patch(
            "giga_agent.modules.mem_zero_memory.module.event_bus.subscribe",
            Mock(),
        ) as mocked_subscribe:
            import giga_agent.modules.mem_zero_memory.module as mem_module

            mem_module._MEM0_EMBEDDING_SUBSCRIBED = False
            try:
                await module.on_startup(session=object())
                await module.on_startup(session=object())
            finally:
                mem_module._MEM0_EMBEDDING_SUBSCRIBED = False

        mocked_subscribe.assert_called_once()
