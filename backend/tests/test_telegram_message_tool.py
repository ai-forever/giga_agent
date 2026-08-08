import json
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from giga_agent.channels.telegram.app import TelegramBotApp
from giga_agent.channels.telegram.message_tool import (
    TELEGRAM_MESSAGE_TOOL_NAME,
    build_telegram_message_tool_schema,
    parse_telegram_message_tool_payload,
)
from giga_agent.channels.telegram.services.message_tool_runtime import (
    _build_prompt_reply_markup,
)


def _bot_app() -> TelegramBotApp:
    bot_row = types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_token="123456:telegram-test-token",
        bot_username="test_bot",
    )
    app = TelegramBotApp(bot_row=bot_row, user_email="owner@example.com")
    app.bot.send_rich_message = AsyncMock()
    return app


def _message(
    text: str = "hello",
    *,
    message_id: int = 77,
    chat_id: int = 42,
    chat_type: str = "private",
    chat_title: str | None = None,
    chat_username: str | None = None,
    from_user_id: int = 1001,
    from_username: str = "telegram_user",
    from_first_name: str = "Telegram",
    from_last_name: str = "User",
    entities: list[types.SimpleNamespace] | None = None,
    caption_entities: list[types.SimpleNamespace] | None = None,
    reply_to_message: types.SimpleNamespace | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        text=text,
        caption=None,
        entities=entities,
        caption_entities=caption_entities,
        photo=None,
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        sticker=None,
        message_id=message_id,
        chat=types.SimpleNamespace(
            id=chat_id,
            type=chat_type,
            title=chat_title,
            username=chat_username,
            first_name=from_first_name if chat_type == "private" else None,
            last_name=from_last_name if chat_type == "private" else None,
            do=AsyncMock(),
        ),
        from_user=types.SimpleNamespace(
            id=from_user_id,
            username=from_username,
            first_name=from_first_name,
            last_name=from_last_name,
        ),
        reply_to_message=reply_to_message,
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_document=AsyncMock(),
        answer_audio=AsyncMock(),
        answer_video=AsyncMock(),
    )


class TelegramMessageToolTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_payload_unescapes_literal_newlines(self):
        payload = parse_telegram_message_tool_payload(
            {"content": "Первая строка\\n\\nВторая строка"}
        )

        self.assertEqual(payload.content, "Первая строка\n\nВторая строка")

    def test_parse_payload_keeps_regular_text(self):
        payload = parse_telegram_message_tool_payload(
            {"content": "Обычный текст\nс реальным переносом"}
        )

        self.assertEqual(payload.content, "Обычный текст\nс реальным переносом")

    def test_parse_payload_unescapes_html_entities(self):
        payload = parse_telegram_message_tool_payload(
            {
                "content": "Толпа кричит: &quot;Еще!&quot;",
                "buttons": [{"text": "Сказать &quot;да&quot;"}],
            }
        )

        self.assertEqual(payload.content, 'Толпа кричит: "Еще!"')
        self.assertEqual(payload.buttons[0].text, 'Сказать "да"')

    def test_schema_is_json_schema_safe(self):
        schema = build_telegram_message_tool_schema()
        serialized = json.dumps(schema, ensure_ascii=False)
        button_properties = schema["inputSchema"]["properties"]["buttons"]["items"][
            "properties"
        ]

        self.assertEqual(schema["name"], TELEGRAM_MESSAGE_TOOL_NAME)
        self.assertIn("inputSchema", schema)
        self.assertNotIn("anyOf", serialized)
        self.assertNotIn("row", button_properties)

    async def test_continue_run_sends_prompt_for_pending_message_interrupt(self):
        app = _bot_app()
        message = _message()
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Какой вариант выбрать?"},
        }
        client = types.SimpleNamespace(runs=types.SimpleNamespace(wait=AsyncMock()))

        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[pending_call]
        )
        app.message_tool_runtime.send_message_tool_prompt = AsyncMock()

        result = await app.message_tool_runtime.continue_run_until_ready(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            result={
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [pending_call],
                    },
                ],
            },
            run_timeout=30,
        )

        self.assertIsNone(result)
        app.message_tool_runtime.send_message_tool_prompt.assert_awaited_once_with(
            message,
            "token",
            pending_call,
            None,
            include_reply_markup=True,
        )
        client.runs.wait.assert_not_awaited()

    async def test_continue_run_sends_all_pending_message_interrupts(self):
        app = _bot_app()
        message = _message()
        first_pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Сначала покажи инструкцию"},
        }
        second_pending_call = {
            "id": "call-2",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Теперь задай вопрос"},
        }
        client = types.SimpleNamespace(runs=types.SimpleNamespace(wait=AsyncMock()))

        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[first_pending_call, second_pending_call]
        )
        app.message_tool_runtime.send_message_tool_prompt = AsyncMock()

        result = await app.message_tool_runtime.continue_run_until_ready(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            result={
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [first_pending_call, second_pending_call],
                    },
                ],
            },
            run_timeout=30,
        )

        self.assertIsNone(result)
        self.assertEqual(
            app.message_tool_runtime.send_message_tool_prompt.await_count, 2
        )
        self.assertEqual(
            app.message_tool_runtime.send_message_tool_prompt.await_args_list,
            [
                unittest.mock.call(
                    message,
                    "token",
                    first_pending_call,
                    None,
                    include_reply_markup=False,
                ),
                unittest.mock.call(
                    message,
                    "token",
                    second_pending_call,
                    None,
                    include_reply_markup=True,
                ),
            ],
        )
        client.runs.wait.assert_not_awaited()

    async def test_continue_run_auto_resumes_when_expect_response_false(self):
        app = _bot_app()
        message = _message()
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": "Сейчас просто покажу статус",
                "expect_response": False,
            },
        }
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={"messages": [{"type": "ai", "content": "ok"}]},
                ),
            ),
        )

        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            side_effect=[[pending_call], []],
        )
        app.message_tool_runtime.send_message_tool_prompt = AsyncMock()

        result = await app.message_tool_runtime.continue_run_until_ready(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            result={
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [pending_call],
                    },
                ],
            },
            run_timeout=30,
        )

        self.assertEqual(result, {"messages": [{"type": "ai", "content": "ok"}]})
        app.message_tool_runtime.send_message_tool_prompt.assert_awaited_once_with(
            message,
            "token",
            pending_call,
            None,
            include_reply_markup=True,
        )
        resume_payload = client.runs.wait.await_args.kwargs["command"]["resume"]
        self.assertEqual(resume_payload["type"], "tool_call")
        payload = json.loads(
            resume_payload["results"][0]["result"]["content"][0]["text"]
        )
        self.assertEqual(payload["content"], "")
        self.assertFalse(payload["expect_response"])
        self.assertIn("Уведомление доставлено пользователю", payload["message"])
        self.assertNotIn("telegram_chat_id", payload)

    async def test_resume_pending_message_tool_builds_tool_result_payload(self):
        app = _bot_app()
        message = _message("Да")
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": "Подтверди действие",
                "buttons": [{"text": "Да", "kind": "callback"}],
                "response_format": "single_choice",
            },
        }
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={"messages": [{"type": "ai", "content": "ok"}]}
                ),
            ),
        )

        app.media_service.collect_incoming_files = AsyncMock(
            return_value=[
                {
                    "path": "/bucket/reply.txt",
                    "original_name": "reply.txt",
                    "file_type": "other",
                    "size": 3,
                },
            ],
        )
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "ok"}]},
        )

        result = await app.message_tool_runtime.resume_pending_message_tool(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            pending_tool_calls=[pending_call],
            run_timeout=30,
        )

        self.assertEqual(result, {"messages": [{"type": "ai", "content": "ok"}]})
        resume_payload = client.runs.wait.await_args.kwargs["command"]["resume"]
        self.assertEqual(resume_payload["type"], "tool_call")
        self.assertEqual(resume_payload["results"][0]["id"], "call-1")

        content = resume_payload["results"][0]["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        payload = json.loads(content[0]["text"])
        self.assertEqual(payload["content"], "Да")
        self.assertEqual(payload["selected_button"], "Да")
        self.assertEqual(payload["response_format"], "single_choice")
        self.assertEqual(payload["files"][0]["path"], "/bucket/reply.txt")
        self.assertEqual(payload["attachments"], ["/bucket/reply.txt"])
        self.assertEqual(payload["message_context"]["text"], "Да")
        self.assertEqual(
            payload["message_context"]["attachments"],
            ["/bucket/reply.txt"],
        )
        self.assertEqual(payload["reply"], {})

    async def test_resume_pending_message_tool_includes_attachments_from_message_and_reply(
        self,
    ):
        app = _bot_app()
        reply_message = _message(
            "Смотри сюда ![ref](attachment:/bucket/reply/ref.png)",
            message_id=76,
        )
        message = _message(
            "Используй ![doc](attachment:/bucket/current/doc.pdf)",
            reply_to_message=reply_message,
        )
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Ответь с учетом вложений"},
        }
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={"messages": [{"type": "ai", "content": "ok"}]}
                )
            )
        )

        app.media_service.collect_incoming_files = AsyncMock(
            side_effect=[
                [
                    {
                        "path": "/bucket/reply/uploaded.pdf",
                        "original_name": "uploaded.pdf",
                        "file_type": "other",
                        "size": 7,
                    }
                ],
                [
                    {
                        "path": "/bucket/current/uploaded.jpg",
                        "original_name": "uploaded.jpg",
                        "file_type": "image",
                        "size": 9,
                    }
                ],
            ]
        )
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "ok"}]},
        )

        result = await app.message_tool_runtime.resume_pending_message_tool(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            pending_tool_calls=[pending_call],
            run_timeout=30,
        )

        self.assertEqual(result, {"messages": [{"type": "ai", "content": "ok"}]})
        resume_payload = client.runs.wait.await_args.kwargs["command"]["resume"]
        payload = json.loads(
            resume_payload["results"][0]["result"]["content"][0]["text"]
        )
        self.assertEqual(
            payload["attachments"],
            ["/bucket/current/uploaded.jpg"],
        )
        self.assertEqual(payload["message_context"]["text"], message.text)
        self.assertEqual(
            payload["message_context"]["attachments"],
            ["/bucket/current/uploaded.jpg"],
        )
        self.assertEqual(payload["reply"]["text"], reply_message.text)
        self.assertEqual(
            payload["reply"]["attachments"],
            ["/bucket/reply/uploaded.pdf"],
        )
        self.assertEqual(
            payload["reply"]["files"][0]["path"],
            "/bucket/reply/uploaded.pdf",
        )

    async def test_resume_pending_message_tool_fills_only_last_tool_call(self):
        app = _bot_app()
        message = _message("Финальный ответ")
        first_pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Сначала отправь уведомление"},
        }
        second_pending_call = {
            "id": "call-2",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Теперь ответь на вопрос"},
        }
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={"messages": [{"type": "ai", "content": "ok"}]}
                )
            )
        )

        app.media_service.collect_incoming_files = AsyncMock(return_value=[])
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "ok"}]},
        )

        result = await app.message_tool_runtime.resume_pending_message_tool(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            pending_tool_calls=[first_pending_call, second_pending_call],
            run_timeout=30,
        )

        self.assertEqual(result, {"messages": [{"type": "ai", "content": "ok"}]})
        resume_payload = client.runs.wait.await_args.kwargs["command"]["resume"]
        self.assertEqual(
            [tool_result["id"] for tool_result in resume_payload["results"]],
            ["call-1", "call-2"],
        )
        self.assertEqual(resume_payload["results"][0]["result"], {})
        second_payload = json.loads(
            resume_payload["results"][1]["result"]["content"][0]["text"]
        )
        self.assertEqual(second_payload["content"], "Финальный ответ")
        self.assertEqual(second_payload["telegram_chat_id"], message.chat.id)

    def test_build_prompt_reply_markup_uses_inline_buttons_only(self):
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Да", kind="callback", url=""),
                types.SimpleNamespace(
                    text="Документация", kind="url", url="https://example.com"
                ),
            ],
        )

        markup = _build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "ga_msg:0")
        self.assertEqual(markup.inline_keyboard[0][1].url, "https://example.com")

    def test_build_prompt_reply_markup_wraps_after_four_buttons(self):
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Да", kind="callback", url=""),
                types.SimpleNamespace(text="Нет", kind="callback", url=""),
                types.SimpleNamespace(text="Ок", kind="callback", url=""),
                types.SimpleNamespace(text="Еще", kind="callback", url=""),
                types.SimpleNamespace(text="Позже", kind="callback", url=""),
            ],
        )

        markup = _build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(len(markup.inline_keyboard[0]), 4)
        self.assertEqual(len(markup.inline_keyboard[1]), 1)

    def test_build_prompt_reply_markup_wraps_when_row_text_too_long(self):
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Коротко", kind="callback", url=""),
                types.SimpleNamespace(
                    text="Очень длинная кнопка", kind="callback", url=""
                ),
            ],
        )

        markup = _build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(markup.inline_keyboard[0][0].text, "Коротко")
        self.assertEqual(markup.inline_keyboard[1][0].text, "Очень длинная кнопка")

    def test_should_process_message_ignores_group_message_without_mention(self):
        app = _bot_app()
        message = _message(
            "Всем привет",
            chat_type="group",
            chat_title="Ops Room",
        )

        self.assertFalse(app.access_service.should_process_message(message))

    def test_should_process_message_accepts_group_message_with_mention(self):
        app = _bot_app()
        message = _message(
            "@test_bot помоги",
            chat_type="supergroup",
            chat_title="Ops Room",
            entities=[
                types.SimpleNamespace(
                    type="mention",
                    offset=0,
                    length=len("@test_bot"),
                )
            ],
        )

        self.assertTrue(app.access_service.should_process_message(message))

    def test_strip_bot_mentions_removes_bot_tag_from_text(self):
        app = _bot_app()

        self.assertEqual(
            app.access_service.strip_bot_mentions("@test_bot помоги с отчётом"),
            "помоги с отчётом",
        )

    async def test_set_commands_registers_private_and_group_scopes(self):
        app = _bot_app()
        app.bot.set_my_commands = AsyncMock()

        await app.set_commands()

        self.assertEqual(app.bot.set_my_commands.await_count, 2)

        private_call = app.bot.set_my_commands.await_args_list[0]
        private_commands = private_call.args[0]
        private_scope = private_call.kwargs["scope"]
        self.assertIsInstance(private_scope, BotCommandScopeAllPrivateChats)
        self.assertEqual(
            [command.command for command in private_commands],
            ["start", "new", "message"],
        )

        group_call = app.bot.set_my_commands.await_args_list[1]
        group_commands = group_call.args[0]
        group_scope = group_call.kwargs["scope"]
        self.assertIsInstance(group_scope, BotCommandScopeAllGroupChats)
        self.assertEqual(
            [command.command for command in group_commands],
            ["new", "message"],
        )

    async def test_handle_message_command_requires_text_or_attachment(self):
        app = _bot_app()
        message = _message("/message", chat_type="supergroup", chat_title="Ops Room")

        await app.handle_message_command(message)

        message.answer.assert_awaited_once_with(
            "После /message нужен текст или вложение для обработки."
        )

    async def test_handle_message_command_processes_text_after_command(self):
        app = _bot_app()
        command_message = _message(
            "/message Помоги с задачей",
            chat_id=-1001234567890,
            chat_type="supergroup",
            chat_title="Ops Room",
            message_id=92,
        )
        app.message_handlers.handle_message = AsyncMock()

        await app.handle_message_command(command_message)

        app.message_handlers.handle_message.assert_awaited_once_with(
            command_message,
            force_process=True,
            text_override="Помоги с задачей",
        )

    async def test_handle_message_command_allows_attachments_without_text(self):
        app = _bot_app()
        command_message = _message(
            "/message",
            chat_id=-1001234567890,
            chat_type="supergroup",
            chat_title="Ops Room",
            message_id=92,
        )
        command_message.document = types.SimpleNamespace(
            file_id="doc-1", file_name="task.txt"
        )
        app.message_handlers.handle_message = AsyncMock()

        await app.handle_message_command(command_message)

        app.message_handlers.handle_message.assert_awaited_once_with(
            command_message,
            force_process=True,
            text_override="",
        )

    async def test_handle_message_command_allows_reply_content_without_text(self):
        app = _bot_app()
        reply_message = _message(
            "Посмотри на это сообщение",
            message_id=91,
            chat_id=-1001234567890,
            chat_type="supergroup",
            chat_title="Ops Room",
        )
        command_message = _message(
            "/message",
            chat_id=-1001234567890,
            chat_type="supergroup",
            chat_title="Ops Room",
            message_id=92,
            reply_to_message=reply_message,
        )
        app.message_handlers.handle_message = AsyncMock()

        await app.handle_message_command(command_message)

        app.message_handlers.handle_message.assert_awaited_once_with(
            command_message,
            force_process=True,
            text_override="",
        )

    async def test_handle_callback_query_resumes_message_tool(self):
        app = _bot_app()
        message = _message("")
        callback = types.SimpleNamespace(
            data="ga_msg:0",
            message=message,
            from_user=message.from_user,
            answer=AsyncMock(),
        )
        contact = types.SimpleNamespace(is_approved=True)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": "Выбери вариант",
                "buttons": [{"text": "Да", "kind": "callback", "value": "confirm"}],
            },
        }
        client = types.SimpleNamespace()

        @asynccontextmanager
        async def _session_context():
            yield object()

        client.aclose = AsyncMock()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock(return_value="thread-1")
        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[pending_call]
        )
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "Готово"}]},
        )
        app.message_tool_runtime.resume_message_tool_calls = AsyncMock(
            return_value={"messages": []}
        )
        app.media_service.send_run_result = AsyncMock()
        app.thread_service.create_client = lambda token: client
        app.thread_service.create_token = lambda: "token"

        with (
            patch(
                "giga_agent.channels.telegram.handlers.callbacks.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.callbacks.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_callback_query(callback)

        callback.answer.assert_awaited()
        app.message_tool_runtime.resume_message_tool_calls.assert_awaited_once()
        app.media_service.send_run_result.assert_awaited_once()
        kwargs = app.message_tool_runtime.resume_message_tool_calls.await_args.kwargs
        self.assertEqual(kwargs["response_text"], "confirm")
        self.assertEqual(kwargs["selected_button"], "Да")

    async def test_register_contact_uses_group_chat_metadata(self):
        app = _bot_app()
        message = _message(
            "hello",
            chat_id=-1001234567890,
            chat_type="supergroup",
            chat_title="GigaAgent Team",
            chat_username="giga_agent_team",
            from_user_id=5001,
        )
        repo = types.SimpleNamespace(upsert_contact=AsyncMock())

        @asynccontextmanager
        async def _session_context():
            yield object()

        with (
            patch(
                "giga_agent.channels.telegram.services.access.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.services.access.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.access_service.register_contact(message)

        repo.upsert_contact.assert_awaited_once_with(
            bot_id=app.bot_row.id,
            external_chat_id="-1001234567890",
            external_user_id=None,
            chat_type="supergroup",
            chat_title="GigaAgent Team",
            username="giga_agent_team",
            first_name=None,
            last_name=None,
        )

    async def test_handle_callback_query_blocks_unapproved_group_chat(self):
        app = _bot_app()
        message = _message(
            "",
            chat_id=-1002003004005,
            chat_type="group",
            chat_title="Ops Room",
            from_user_id=7001,
        )
        callback = types.SimpleNamespace(
            data="ga_msg:0",
            message=message,
            answer=AsyncMock(),
        )
        contact = types.SimpleNamespace(is_approved=False)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock()
        app.message_tool_runtime.resume_message_tool_calls = AsyncMock()

        with (
            patch(
                "giga_agent.channels.telegram.handlers.callbacks.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.callbacks.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_callback_query(callback)

        callback.answer.assert_awaited_once_with(
            "Контакт не подтверждён",
            show_alert=True,
        )
        app.thread_service.get_or_create_thread.assert_not_awaited()
        app.message_tool_runtime.resume_message_tool_calls.assert_not_awaited()

    async def test_handle_message_injects_message_tool_schema_into_run_input(self):
        app = _bot_app()
        message = _message("Привет")
        contact = types.SimpleNamespace(is_approved=True)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={
                        "messages": [
                            {"type": "human", "content": "Привет"},
                            {"type": "ai", "content": "Здравствуйте!"},
                        ],
                    },
                ),
            ),
            aclose=AsyncMock(),
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock(return_value="thread-1")
        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[]
        )
        app.media_service.collect_incoming_files = AsyncMock(return_value=[])
        app.thread_service.load_collections_payload = AsyncMock(return_value=[])
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            side_effect=lambda **kwargs: kwargs["result"],
        )
        app.thread_service.create_client = lambda token: client
        app.thread_service.create_token = lambda: "token"

        with (
            patch(
                "giga_agent.channels.telegram.handlers.messages.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.messages.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_message(message)

        run_input = client.runs.wait.await_args.kwargs["input"]
        self.assertIn("mcp_tools", run_input)
        self.assertEqual(run_input["mcp_tools"], [build_telegram_message_tool_schema()])
        self.assertEqual(run_input["messages"][0]["role"], "human")
        app.bot.send_rich_message.assert_awaited()

    async def test_handle_message_includes_reply_context_and_sender_metadata(self):
        app = _bot_app()
        reply_message = _message(
            "Исходное сообщение",
            message_id=76,
            from_user_id=2001,
            from_username="alice",
            from_first_name="Alice",
            from_last_name="A",
        )
        message = _message(
            "Ответ с уточнением",
            reply_to_message=reply_message,
            from_user_id=2002,
            from_username="bob",
            from_first_name="Bob",
            from_last_name="B",
        )
        contact = types.SimpleNamespace(is_approved=True)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    return_value={
                        "messages": [
                            {"type": "human", "content": "ok"},
                            {"type": "ai", "content": "Готово"},
                        ],
                    }
                )
            ),
            aclose=AsyncMock(),
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock(return_value="thread-1")
        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[]
        )
        app.media_service.collect_incoming_files = AsyncMock(
            side_effect=[
                [
                    {
                        "path": "/bucket/reply/report.pdf",
                        "original_name": "report.pdf",
                        "file_type": "other",
                        "size": 10,
                    }
                ],
                [
                    {
                        "path": "/bucket/current/photo.jpg",
                        "original_name": "photo.jpg",
                        "file_type": "image",
                        "size": 20,
                    }
                ],
            ]
        )
        app.thread_service.load_collections_payload = AsyncMock(return_value=[])
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            side_effect=lambda **kwargs: kwargs["result"]
        )
        app.thread_service.create_client = lambda token: client
        app.thread_service.create_token = lambda: "token"

        with (
            patch(
                "giga_agent.channels.telegram.handlers.messages.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.messages.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_message(message)

        run_input = client.runs.wait.await_args.kwargs["input"]
        human_message = run_input["messages"][0]
        self.assertIn("Прикреплено сообщение:", human_message["content"])
        self.assertIn("Ник: @alice", human_message["content"])
        self.assertIn("Имя: Alice A", human_message["content"])
        self.assertIn("Исходное сообщение", human_message["content"])
        self.assertIn("Входящее сообщение", human_message["content"])
        self.assertIn("Ник: @bob", human_message["content"])
        self.assertIn("Имя: Bob B", human_message["content"])
        self.assertIn("Ответ с уточнением", human_message["content"])
        self.assertEqual(
            human_message["additional_kwargs"]["files"],
            [
                {
                    "path": "/bucket/reply/report.pdf",
                    "original_name": "report.pdf",
                    "file_type": "other",
                    "size": 10,
                },
                {
                    "path": "/bucket/current/photo.jpg",
                    "original_name": "photo.jpg",
                    "file_type": "image",
                    "size": 20,
                },
            ],
        )

    async def test_handle_message_asks_user_to_wait_for_running_bot(self):
        app = _bot_app()
        message = _message("Привет")
        contact = types.SimpleNamespace(is_approved=True)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(),
                list=AsyncMock(
                    side_effect=[
                        [{"run_id": "run-1", "status": "running"}],
                    ]
                ),
            ),
            aclose=AsyncMock(),
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock(return_value="thread-1")
        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[]
        )
        app.thread_service.create_client = lambda token: client
        app.thread_service.create_token = lambda: "token"

        with (
            patch(
                "giga_agent.channels.telegram.handlers.messages.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.messages.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_message(message)

        message.answer.assert_awaited_once_with(
            "⏳ Бот ещё обрабатывает предыдущее сообщение. "
            "Дождитесь завершения работы и попробуйте снова."
        )
        client.runs.wait.assert_not_awaited()
        message.chat.do.assert_not_awaited()

    async def test_handle_message_blocks_unapproved_group_chat(self):
        app = _bot_app()
        message = _message(
            "@test_bot Привет, команда",
            chat_id=-1005550001112,
            chat_type="supergroup",
            chat_title="GigaAgent QA",
            from_user_id=3101,
            entities=[
                types.SimpleNamespace(
                    type="mention",
                    offset=0,
                    length=len("@test_bot"),
                )
            ],
        )
        contact = types.SimpleNamespace(is_approved=False)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        client = types.SimpleNamespace(runs=types.SimpleNamespace(wait=AsyncMock()))

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock()

        with (
            patch(
                "giga_agent.channels.telegram.handlers.messages.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.messages.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_message(message)

        message.answer.assert_awaited_once_with(
            "⏳ Ваш контакт ожидает подтверждения. "
            "Владелец бота должен одобрить вас в настройках."
        )
        app.thread_service.get_or_create_thread.assert_not_awaited()
        client.runs.wait.assert_not_awaited()

    async def test_handle_message_uses_shared_group_chat_access_for_different_users(
        self,
    ):
        app = _bot_app()
        group_chat_id = -1005550001113
        first_message = _message(
            "@test_bot Первый участник",
            chat_id=group_chat_id,
            chat_type="supergroup",
            chat_title="GigaAgent QA",
            from_user_id=3101,
            from_username="alice",
            from_first_name="Alice",
            from_last_name="A",
            entities=[
                types.SimpleNamespace(
                    type="mention",
                    offset=0,
                    length=len("@test_bot"),
                )
            ],
        )
        second_message = _message(
            "@test_bot Второй участник",
            chat_id=group_chat_id,
            chat_type="supergroup",
            chat_title="GigaAgent QA",
            from_user_id=3102,
            from_username="bob",
            from_first_name="Bob",
            from_last_name="B",
            entities=[
                types.SimpleNamespace(
                    type="mention",
                    offset=0,
                    length=len("@test_bot"),
                )
            ],
        )
        contact = types.SimpleNamespace(is_approved=True)
        repo = types.SimpleNamespace(get_contact=AsyncMock(return_value=contact))
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                wait=AsyncMock(
                    side_effect=[
                        {
                            "messages": [
                                {"type": "human", "content": "Первый участник"},
                                {"type": "ai", "content": "Ответ 1"},
                            ],
                        },
                        {
                            "messages": [
                                {"type": "human", "content": "Второй участник"},
                                {"type": "ai", "content": "Ответ 2"},
                            ],
                        },
                    ]
                ),
            ),
            aclose=AsyncMock(),
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock(return_value="thread-group")
        app.message_tool_runtime.get_pending_message_tool_calls = AsyncMock(
            return_value=[]
        )
        app.media_service.collect_incoming_files = AsyncMock(return_value=[])
        app.thread_service.load_collections_payload = AsyncMock(return_value=[])
        app.message_tool_runtime.continue_run_until_ready = AsyncMock(
            side_effect=lambda **kwargs: kwargs["result"]
        )
        app.thread_service.create_client = lambda token: client
        app.thread_service.create_token = lambda: "token"

        with (
            patch(
                "giga_agent.channels.telegram.handlers.messages.get_session_factory",
                AsyncMock(return_value=lambda: _session_context()),
            ),
            patch(
                "giga_agent.channels.telegram.handlers.messages.ChannelBotRepository",
                return_value=repo,
            ),
        ):
            await app.handle_message(first_message)
            await app.handle_message(second_message)

        self.assertEqual(repo.get_contact.await_count, 2)
        self.assertEqual(
            repo.get_contact.await_args_list,
            [
                unittest.mock.call(app.bot_row.id, str(group_chat_id)),
                unittest.mock.call(app.bot_row.id, str(group_chat_id)),
            ],
        )
        self.assertEqual(
            app.thread_service.get_or_create_thread.await_args_list,
            [
                unittest.mock.call(client, repo, group_chat_id, "3101"),
                unittest.mock.call(client, repo, group_chat_id, "3102"),
            ],
        )
        self.assertEqual(client.runs.wait.await_count, 2)
        self.assertEqual(app.bot.send_rich_message.await_count, 2)

    async def test_handle_message_ignores_group_message_without_mention(self):
        app = _bot_app()
        message = _message(
            "Привет, команда",
            chat_id=-1005550001114,
            chat_type="supergroup",
            chat_title="GigaAgent QA",
            from_user_id=3101,
        )
        app.access_service.register_contact = AsyncMock()
        app.thread_service.get_or_create_thread = AsyncMock()
        await app.handle_message(message)

        app.access_service.register_contact.assert_not_awaited()
        app.thread_service.get_or_create_thread.assert_not_awaited()
        message.answer.assert_not_awaited()

    async def test_send_message_tool_prompt_renders_plotly_json_as_photo(self):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b'{"data": []}')
        tool_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": "Готово",
                "attachments": [
                    {
                        "path": "/bucket/chart.plotly.json",
                        "kind": "document",
                    },
                ],
            },
        }

        with patch(
            "giga_agent.channels.telegram.services.message_tool_runtime._convert_plotly_attachment",
            return_value=(b"png-bytes", "chart.png", True),
        ):
            await app.message_tool_runtime.send_message_tool_prompt(
                message, "token", tool_call
            )

        message.answer_photo.assert_awaited_once()
        message.answer_document.assert_not_awaited()

    async def test_send_message_tool_prompt_skips_duplicate_attachment_from_content(
        self,
    ):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b"image-bytes")
        tool_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": (
                    "Вот изображение:\n\n"
                    "![copy](attachment:/bucket/generated/image.png)"
                ),
                "attachments": [
                    {
                        "path": "/bucket/generated/image.png",
                        "kind": "image",
                    },
                ],
            },
        }

        await app.message_tool_runtime.send_message_tool_prompt(
            message, "token", tool_call
        )

        message.answer_photo.assert_awaited_once()
        app.media_service.download_attachment.assert_awaited_once_with(
            "token", "/bucket/generated/image.png"
        )

    async def test_send_message_tool_prompt_preserves_content_part_order(self):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b"image-bytes")
        events: list[tuple[str, str]] = []

        async def _record_text(_chat_id, rich_message, *args, **kwargs):
            events.append(("text", rich_message.markdown))

        async def _record_photo(*args, **kwargs):
            events.append(("photo", "image"))

        app.bot.send_rich_message.side_effect = _record_text
        message.answer_photo.side_effect = _record_photo
        tool_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": (
                    "тест\n![test](attachment:/bucket/generated/image.png)\nтест"
                ),
            },
        }

        await app.message_tool_runtime.send_message_tool_prompt(
            message, "token", tool_call
        )

        self.assertEqual(
            events,
            [
                ("text", "тест"),
                ("photo", "image"),
                ("text", "тест"),
            ],
        )

    async def test_send_message_tool_prompt_deduplicates_prompt_attachment_and_content_part(
        self,
    ):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b"image-bytes")
        events: list[str] = []

        async def _record_text(_chat_id, rich_message, *args, **kwargs):
            events.append(f"text:{rich_message.markdown}")

        async def _record_photo(*args, **kwargs):
            events.append("photo")

        app.bot.send_rich_message.side_effect = _record_text
        message.answer_photo.side_effect = _record_photo
        tool_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {
                "content": (
                    "до\n![copy](attachment:/bucket/generated/image.png)\nпосле"
                ),
                "attachments": [
                    {
                        "path": "/bucket/generated/image.png",
                        "kind": "image",
                    },
                ],
            },
        }

        await app.message_tool_runtime.send_message_tool_prompt(
            message, "token", tool_call
        )

        self.assertEqual(events, ["photo", "text:до", "text:после"])
        self.assertEqual(message.answer_photo.await_count, 1)

    async def test_send_run_result_renders_plotly_json_as_photo(self):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b'{"data": []}')
        result = {
            "messages": [
                {"type": "human", "content": "Покажи график"},
                {
                    "type": "ai",
                    "content": "![graph](attachment:/bucket/chart.plotly.json)",
                },
            ],
        }

        with patch(
            "giga_agent.channels.telegram.services.media._convert_plotly_attachment",
            return_value=(b"png-bytes", "chart.png", True),
        ):
            await app.media_service.send_run_result(
                message=message,
                token="token",
                result=result,
                request_start=object(),
            )

        message.answer_photo.assert_awaited_once()
        message.answer_document.assert_not_awaited()

    async def test_send_run_result_preserves_content_part_order(self):
        app = _bot_app()
        message = _message()
        app.media_service.download_attachment = AsyncMock(return_value=b"image-bytes")
        events: list[tuple[str, str]] = []

        async def _record_text(_chat_id, rich_message, *args, **kwargs):
            events.append(("text", rich_message.markdown))

        async def _record_photo(*args, **kwargs):
            events.append(("photo", "image"))

        app.bot.send_rich_message.side_effect = _record_text
        message.answer_photo.side_effect = _record_photo
        result = {
            "messages": [
                {"type": "human", "content": "Покажи результат"},
                {
                    "type": "ai",
                    "content": (
                        "тест\n![test](attachment:/bucket/generated/image.png)\nтест"
                    ),
                },
            ],
        }

        await app.media_service.send_run_result(
            message=message,
            token="token",
            result=result,
            request_start=object(),
        )

        self.assertEqual(
            events,
            [
                ("text", "тест"),
                ("photo", "image"),
                ("text", "тест"),
            ],
        )

    async def test_send_run_result_replies_to_target_message(self):
        app = _bot_app()
        message = _message()
        result = {
            "messages": [
                {"type": "human", "content": "Покажи статус"},
                {"type": "ai", "content": "Готово"},
            ],
        }

        await app.media_service.send_run_result(
            message=message,
            token="token",
            result=result,
            request_start=object(),
            reply_to_message_id=321,
        )

        reply_parameters = app.bot.send_rich_message.await_args.kwargs[
            "reply_parameters"
        ]
        self.assertEqual(reply_parameters.message_id, 321)
