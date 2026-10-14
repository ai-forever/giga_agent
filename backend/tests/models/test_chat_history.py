import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from aiogram import types as tg_types
from aiogram.methods import (
    EditMessageCaption,
    EditMessageMedia,
    EditMessageText,
    SendMessage,
)
from aiogram.types import InputMediaPhoto
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.channels.telegram.chat_history import (
    ChatHistoryRepository,
    HistoryQuery,
    _query_messages,
    _as_utc,
    archive_outgoing_request,
    get_history_tools,
    normalize_search_text,
)
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import Base
from giga_agent.models.channel import (
    ChannelBot,
    ChannelContact,
    ChannelThread,
    ChatMessage,
)
from giga_agent.models.users import User


class ChatHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            self.owner = User(
                email="history-owner@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(self.owner)
            await session.flush()
            self.bot = ChannelBot(user_id=self.owner.id, channel_type="telegram")
            session.add(self.bot)
            await session.flush()
            self.contact = ChannelContact(
                bot_id=self.bot.id,
                external_chat_id="-1001",
                chat_type="supergroup",
                is_approved=True,
                save_messages=True,
            )
            self.thread = ChannelThread(
                bot_id=self.bot.id,
                external_chat_id="-1001",
                external_user_id="42",
                langgraph_thread_id="history-thread",
            )
            session.add_all((self.contact, self.thread))
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _add(self, message_id: int, message: str, *, seconds: int = 0) -> None:
        async with self.session_factory() as session:
            history = ChatHistoryRepository(session)
            await history.upsert(
                contact_id=self.contact.id,
                message_id=message_id,
                message=message,
                metadata={
                    "sender": {"id": "7", "username": "Ivan_Test"},
                    "content_type": "text",
                },
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(seconds=seconds),
                update_existing=False,
            )
            await session.commit()

    async def test_upsert_keeps_original_date_and_only_edits_when_requested(
        self,
    ) -> None:
        await self._add(1, "Первая версия")
        async with self.session_factory() as session:
            history = ChatHistoryRepository(session)
            await history.upsert(
                contact_id=self.contact.id,
                message_id=1,
                message="Не должна заменить",
                metadata={},
                created_at=datetime.now(timezone.utc),
                update_existing=False,
            )
            await history.upsert(
                contact_id=self.contact.id,
                message_id=1,
                message="Финальная версия",
                metadata={"edited_at": "2026-01-01T00:01:00+00:00"},
                created_at=datetime.now(timezone.utc),
                update_existing=True,
            )
            await session.commit()
            row = await session.scalar(select(ChatMessage))
        assert row is not None
        self.assertEqual(row.message, "Финальная версия")
        self.assertEqual(
            _as_utc(row.created_at), datetime(2026, 1, 1, tzinfo=timezone.utc)
        )

    async def test_query_casefolds_cyrillic_and_uses_tamper_proof_cursor(self) -> None:
        await self._add(1, "ПРИВЕТ мир", seconds=1)
        await self._add(2, "Привет снова", seconds=2)
        await self._add(3, "Другое", seconds=3)
        runtime = types.SimpleNamespace(
            config={"metadata": {"thread_id": "history-thread"}}
        )
        user = types.SimpleNamespace(id=self.owner.id)
        with patch(
            "giga_agent.channels.telegram.chat_history.get_session_factory",
            new=AsyncMock(return_value=self.session_factory),
        ):
            first = await _query_messages(
                user=user,
                runtime=runtime,
                query=HistoryQuery(
                    limit=1,
                    sender_id="7",
                    sender_username="ivan_test",
                    content_type="text",
                ),
                text="привет",
            )
            second = await _query_messages(
                user=user,
                runtime=runtime,
                query=HistoryQuery(
                    limit=1,
                    sender_id="7",
                    sender_username="IVAN_TEST",
                    content_type="text",
                    cursor=first["next_cursor"],
                ),
                text="привет",
            )
            with self.assertRaisesRegex(ValueError, "Invalid cursor"):
                await _query_messages(
                    user=user,
                    runtime=runtime,
                    query=HistoryQuery(
                        limit=1,
                        sender_id="7",
                        sender_username="ivan_test",
                        content_type="text",
                        cursor=first["next_cursor"],
                    ),
                    text="другое",
                )
        self.assertEqual(first["messages"][0]["message_id"], 2)
        self.assertEqual(second["messages"][0]["message_id"], 1)
        self.assertFalse(second["has_more"])

    async def test_find_uses_portable_literal_nfc_casefold_search(self) -> None:
        await self._add(1, "Cafe\u0301: 100% _ 'quoted'")
        runtime = types.SimpleNamespace(
            config={"metadata": {"thread_id": "history-thread"}}
        )
        user = types.SimpleNamespace(id=self.owner.id)
        with patch(
            "giga_agent.channels.telegram.chat_history.get_session_factory",
            new=AsyncMock(return_value=self.session_factory),
        ):
            result = await _query_messages(
                user=user,
                runtime=runtime,
                query=HistoryQuery(),
                text="CAFÉ: 100% _ 'quoted'",
            )
        self.assertEqual([item["message_id"] for item in result["messages"]], [1])

        statement = select(ChatMessage).where(
            ChatMessage.search_text.contains(
                normalize_search_text("CAFÉ: 100% _ 'quoted'"), autoescape=True
            )
        )
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertNotIn("instr", str(compiled).lower())
        self.assertIn("%(search_text_1)s", str(compiled))
        self.assertEqual(compiled.params["search_text_1"], "café: 100/% /_ 'quoted'")

    async def test_later_edit_wins_when_another_session_loaded_the_old_row(
        self,
    ) -> None:
        """An older ORM snapshot must not overwrite a newer committed edit."""
        await self._add(1, "original")
        async with self.session_factory() as older, self.session_factory() as newer:
            # This is the stale snapshot held by the former read-then-write code.
            old_row = await older.scalar(
                select(ChatMessage).where(ChatMessage.message_id == 1)
            )
            assert old_row is not None

            await ChatHistoryRepository(newer).upsert(
                contact_id=self.contact.id,
                message_id=1,
                message="newer edit",
                metadata={"edited_at": "2026-01-01T00:02:00+00:00"},
                created_at=datetime.now(timezone.utc),
                update_existing=True,
            )
            await newer.commit()

            await ChatHistoryRepository(older).upsert(
                contact_id=self.contact.id,
                message_id=1,
                message="older edit",
                metadata={"edited_at": "2026-01-01T00:01:00+00:00"},
                created_at=datetime.now(timezone.utc),
                update_existing=True,
            )
            await older.commit()

        async with self.session_factory() as verify:
            row = await verify.scalar(
                select(ChatMessage).where(ChatMessage.message_id == 1)
            )
        assert row is not None
        self.assertEqual(row.message, "newer edit")

    @staticmethod
    def _telegram_message(*, text: str | None = None, caption: str | None = None):
        now = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "message_id": 11,
            "date": now,
            "edit_date": now,
            "chat": {"id": -1001, "type": "supergroup"},
        }
        if text is not None:
            payload["text"] = text
        if caption is not None:
            payload["caption"] = caption
            payload["photo"] = [
                {
                    "file_id": "photo-id",
                    "file_unique_id": "photo-unique-id",
                    "width": 1,
                    "height": 1,
                }
            ]
        return tg_types.Message.model_validate(payload)

    async def test_outgoing_text_caption_and_media_edits_update_archive(self) -> None:
        cases = (
            (EditMessageText(chat_id=-1001, message_id=11, text="updated"), "updated"),
            (
                EditMessageCaption(chat_id=-1001, message_id=11, caption="updated"),
                None,
            ),
            (
                EditMessageMedia(
                    chat_id=-1001,
                    message_id=11,
                    media=InputMediaPhoto(media="photo-id"),
                ),
                "updated",
            ),
        )
        for method, text_value in cases:
            message = self._telegram_message(text=text_value, caption="updated")
            archive = AsyncMock()
            with (
                self.subTest(method=type(method).__name__),
                patch(
                    "giga_agent.channels.telegram.chat_history.archive_telegram_message",
                    archive,
                ),
            ):
                result = await archive_outgoing_request(
                    AsyncMock(return_value=message),
                    types.SimpleNamespace(),
                    method,
                    bot_row=self.bot,
                )
            self.assertIs(result, message)
            archive.assert_awaited_once_with(
                bot_row=self.bot,
                message=message,
                direction="outgoing",
                edited=True,
            )

    async def test_outgoing_send_then_text_edit_replaces_archived_message(self) -> None:
        original = self._telegram_message(text="original")
        edited = self._telegram_message(text="edited")
        with patch(
            "giga_agent.channels.telegram.chat_history.get_session_factory",
            new=AsyncMock(return_value=self.session_factory),
        ):
            await archive_outgoing_request(
                AsyncMock(return_value=original),
                types.SimpleNamespace(),
                SendMessage(chat_id=-1001, text="original"),
                bot_row=self.bot,
            )
            await archive_outgoing_request(
                AsyncMock(return_value=edited),
                types.SimpleNamespace(),
                EditMessageText(chat_id=-1001, message_id=11, text="edited"),
                bot_row=self.bot,
            )
        async with self.session_factory() as session:
            row = await session.scalar(
                select(ChatMessage).where(ChatMessage.message_id == 11)
            )
        assert row is not None
        self.assertEqual(row.message, "edited")
        self.assertIn("edited_at", row.message_metadata)

    async def test_outgoing_archive_error_does_not_repeat_or_fail_send(self) -> None:
        message = self._telegram_message(text="sent")
        make_request = AsyncMock(return_value=message)
        with patch(
            "giga_agent.channels.telegram.chat_history.archive_telegram_message",
            AsyncMock(side_effect=RuntimeError("storage unavailable")),
        ):
            result = await archive_outgoing_request(
                make_request,
                types.SimpleNamespace(),
                EditMessageText(chat_id=-1001, message_id=11, text="sent"),
                bot_row=self.bot,
            )
        self.assertIs(result, message)
        make_request.assert_awaited_once()

    async def test_history_tools_require_an_approved_group_and_recheck_on_call(
        self,
    ) -> None:
        private_contact = ChannelContact(
            bot_id=self.bot.id,
            external_chat_id="42",
            chat_type="private",
            is_approved=True,
        )
        private_thread = ChannelThread(
            bot_id=self.bot.id,
            external_chat_id="42",
            external_user_id="42",
            langgraph_thread_id="private-history-thread",
        )
        async with self.session_factory() as session:
            session.add_all((private_contact, private_thread))
            await session.commit()

        user = types.SimpleNamespace(id=self.owner.id)
        group_config = {"metadata": {"thread_id": "history-thread"}}
        private_config = {"metadata": {"thread_id": "private-history-thread"}}
        with patch(
            "giga_agent.channels.telegram.chat_history.get_session_factory",
            new=AsyncMock(return_value=self.session_factory),
        ):
            group_tools = await get_history_tools(user, group_config)
            self.assertEqual(len(group_tools), 2)
            self.assertEqual(await get_history_tools(user, private_config), [])
            with self.assertRaisesRegex(ValueError, "История этой группы"):
                await group_tools[0].coroutine(
                    runtime=types.SimpleNamespace(config=private_config)
                )

    async def test_base_agent_adds_history_tools_only_after_server_group_check(
        self,
    ) -> None:
        private_contact = ChannelContact(
            bot_id=self.bot.id,
            external_chat_id="42",
            chat_type="private",
            is_approved=True,
        )
        private_thread = ChannelThread(
            bot_id=self.bot.id,
            external_chat_id="42",
            external_user_id="42",
            langgraph_thread_id="private-history-thread",
        )
        async with self.session_factory() as session:
            contact = await session.get(ChannelContact, self.contact.id)
            assert contact is not None
            contact.save_messages = False
            session.add_all((private_contact, private_thread))
            await session.commit()

        agent = BaseAgent(modules=(), tools=[])
        user = types.SimpleNamespace(id=self.owner.id)
        with (
            patch(
                "giga_agent.core.agent.base.get_thread_metadata",
                new=AsyncMock(return_value={"is_channel": True, "channel": "telegram"}),
            ),
            patch(
                "giga_agent.channels.telegram.chat_history.get_session_factory",
                new=AsyncMock(return_value=self.session_factory),
            ),
        ):
            private_tools = await agent.get_tools(
                user,
                config={"metadata": {"thread_id": "private-history-thread"}},
            )
            group_tools = await agent.get_tools(
                user,
                config={"metadata": {"thread_id": "history-thread"}},
            )
        self.assertEqual(private_tools, [])
        self.assertEqual(
            {tool.name for tool in group_tools}, {"get_messages", "find_messages"}
        )

    async def test_contact_delete_cascades_history(self) -> None:
        await self._add(1, "Удаляемое сообщение")
        async with self.session_factory() as session:
            contact = await session.get(ChannelContact, self.contact.id)
            assert contact is not None
            await session.delete(contact)
            await session.commit()
            self.assertEqual(
                list((await session.scalars(select(ChatMessage))).all()), []
            )

    def test_normalization_and_exact_id_validation(self) -> None:
        self.assertEqual(normalize_search_text("ПРИВЕТ"), "привет")
        with self.assertRaises(ValueError):
            HistoryQuery(message_ids=[])
        with self.assertRaises(ValueError):
            HistoryQuery(message_ids=[1], cursor="cursor")
