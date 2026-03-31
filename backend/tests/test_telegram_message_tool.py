import json
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from giga_agent.modules.telegram.bot import _BotInstance
from giga_agent.modules.telegram.message_tool import (
    TELEGRAM_MESSAGE_TOOL_NAME,
    build_telegram_message_tool_schema,
)


def _bot_instance() -> _BotInstance:
    bot_row = types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_token="123456:telegram-test-token",
        bot_username="test_bot",
    )
    return _BotInstance(bot_row=bot_row, user_email="owner@example.com")


def _message(text: str = "hello") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        text=text,
        caption=None,
        photo=None,
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        sticker=None,
        message_id=77,
        chat=types.SimpleNamespace(id=42, do=AsyncMock()),
        from_user=types.SimpleNamespace(
            id=1001,
            username="telegram_user",
            first_name="Telegram",
            last_name="User",
        ),
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_document=AsyncMock(),
        answer_audio=AsyncMock(),
        answer_video=AsyncMock(),
    )


class TelegramMessageToolTests(unittest.IsolatedAsyncioTestCase):
    def test_schema_is_json_schema_safe(self):
        schema = build_telegram_message_tool_schema()
        serialized = json.dumps(schema, ensure_ascii=False)
        button_properties = schema["inputSchema"]["properties"]["buttons"]["items"]["properties"]

        self.assertEqual(schema["name"], TELEGRAM_MESSAGE_TOOL_NAME)
        self.assertIn("inputSchema", schema)
        self.assertNotIn("anyOf", serialized)
        self.assertNotIn("row", button_properties)

    async def test_continue_run_sends_prompt_for_pending_message_interrupt(self):
        instance = _bot_instance()
        message = _message()
        pending_call = {
            "id": "call-1",
            "name": TELEGRAM_MESSAGE_TOOL_NAME,
            "args": {"content": "Какой вариант выбрать?"},
        }
        client = types.SimpleNamespace(runs=types.SimpleNamespace(wait=AsyncMock()))

        instance._get_pending_message_tool_call = AsyncMock(return_value=pending_call)
        instance._send_message_tool_prompt = AsyncMock()

        result = await instance._continue_run_until_ready(
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
        instance._send_message_tool_prompt.assert_awaited_once_with(
            message,
            "token",
            pending_call,
        )
        client.runs.wait.assert_not_awaited()

    async def test_continue_run_auto_resumes_when_expect_response_false(self):
        instance = _bot_instance()
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

        instance._get_pending_message_tool_call = AsyncMock(
            side_effect=[pending_call, None],
        )
        instance._send_message_tool_prompt = AsyncMock()

        result = await instance._continue_run_until_ready(
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
        instance._send_message_tool_prompt.assert_awaited_once_with(
            message,
            "token",
            pending_call,
        )
        resume_payload = client.runs.wait.await_args.kwargs["command"]["resume"]
        self.assertEqual(resume_payload["type"], "tool_call")
        payload = json.loads(resume_payload["results"][0]["result"]["content"][0]["text"])
        self.assertEqual(payload["content"], "")
        self.assertFalse(payload["expect_response"])
        self.assertIn("expect_response=False", payload["message"])
        self.assertNotIn("telegram_chat_id", payload)

    async def test_resume_pending_message_tool_builds_tool_result_payload(self):
        instance = _bot_instance()
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
                wait=AsyncMock(return_value={"messages": [{"type": "ai", "content": "ok"}]}),
            ),
        )

        instance._collect_incoming_files = AsyncMock(
            return_value=[
                {
                    "path": "/bucket/reply.txt",
                    "original_name": "reply.txt",
                    "file_type": "other",
                    "size": 3,
                },
            ],
        )
        instance._continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "ok"}]},
        )

        result = await instance._resume_pending_message_tool(
            message=message,
            client=client,
            thread_id="thread-1",
            token="token",
            pending_tool_call=pending_call,
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

    def test_build_prompt_reply_markup_uses_inline_buttons_only(self):
        instance = _bot_instance()
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Да", kind="callback", url=""),
                types.SimpleNamespace(text="Документация", kind="url", url="https://example.com"),
            ],
        )

        markup = instance._build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "ga_msg:0")
        self.assertEqual(markup.inline_keyboard[0][1].url, "https://example.com")

    def test_build_prompt_reply_markup_wraps_after_four_buttons(self):
        instance = _bot_instance()
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Да", kind="callback", url=""),
                types.SimpleNamespace(text="Нет", kind="callback", url=""),
                types.SimpleNamespace(text="Ок", kind="callback", url=""),
                types.SimpleNamespace(text="Еще", kind="callback", url=""),
                types.SimpleNamespace(text="Позже", kind="callback", url=""),
            ],
        )

        markup = instance._build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(len(markup.inline_keyboard[0]), 4)
        self.assertEqual(len(markup.inline_keyboard[1]), 1)

    def test_build_prompt_reply_markup_wraps_when_row_text_too_long(self):
        instance = _bot_instance()
        prompt = types.SimpleNamespace(
            buttons=[
                types.SimpleNamespace(text="Коротко", kind="callback", url=""),
                types.SimpleNamespace(text="Очень длинная кнопка", kind="callback", url=""),
            ],
        )

        markup = instance._build_prompt_reply_markup(prompt)

        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(markup.inline_keyboard[0][0].text, "Коротко")
        self.assertEqual(markup.inline_keyboard[1][0].text, "Очень длинная кнопка")

    async def test_handle_callback_query_resumes_message_tool(self):
        instance = _bot_instance()
        message = _message("")
        callback = types.SimpleNamespace(
            data="ga_msg:0",
            message=message,
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

        instance._register_contact = AsyncMock()
        instance._get_or_create_thread = AsyncMock(return_value="thread-1")
        instance._get_pending_message_tool_call = AsyncMock(return_value=pending_call)
        instance._continue_run_until_ready = AsyncMock(
            return_value={"messages": [{"type": "ai", "content": "Готово"}]},
        )
        instance._resume_message_tool_call = AsyncMock(return_value={"messages": []})
        instance._send_run_result = AsyncMock()

        with patch(
            "giga_agent.modules.telegram.bot.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.telegram.bot.TelegramBotRepository",
            return_value=repo,
        ), patch(
            "giga_agent.modules.telegram.bot.get_client",
            return_value=client,
        ), patch(
            "giga_agent.modules.telegram.bot._make_token",
            return_value="token",
        ):
            await instance._handle_callback_query(callback)

        callback.answer.assert_awaited()
        instance._resume_message_tool_call.assert_awaited_once()
        instance._send_run_result.assert_awaited_once()
        kwargs = instance._resume_message_tool_call.await_args.kwargs
        self.assertEqual(kwargs["response_text"], "confirm")
        self.assertEqual(kwargs["selected_button"], "Да")

    async def test_handle_message_injects_message_tool_schema_into_run_input(self):
        instance = _bot_instance()
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
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        instance._register_contact = AsyncMock()
        instance._get_or_create_thread = AsyncMock(return_value="thread-1")
        instance._get_pending_message_tool_call = AsyncMock(return_value=None)
        instance._collect_incoming_files = AsyncMock(return_value=[])
        instance._load_collections_payload = AsyncMock(return_value=[])
        instance._continue_run_until_ready = AsyncMock(
            side_effect=lambda **kwargs: kwargs["result"],
        )

        with patch(
            "giga_agent.modules.telegram.bot.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.telegram.bot.TelegramBotRepository",
            return_value=repo,
        ), patch(
            "giga_agent.modules.telegram.bot.get_client",
            return_value=client,
        ), patch(
            "giga_agent.modules.telegram.bot._make_token",
            return_value="token",
        ):
            await instance._handle_message(message)

        run_input = client.runs.wait.await_args.kwargs["input"]
        self.assertIn("mcp_tools", run_input)
        self.assertEqual(run_input["mcp_tools"], [build_telegram_message_tool_schema()])
        self.assertEqual(run_input["messages"][0]["role"], "human")
        message.answer.assert_awaited()

    async def test_send_message_tool_prompt_renders_plotly_json_as_photo(self):
        instance = _bot_instance()
        message = _message()
        instance._download_attachment = AsyncMock(return_value=b'{"data": []}')
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

        with patch.object(
            instance,
            "_convert_plotly_attachment",
            return_value=(b"png-bytes", "chart.png", True),
        ):
            await instance._send_message_tool_prompt(message, "token", tool_call)

        message.answer_photo.assert_awaited_once()
        message.answer_document.assert_not_awaited()

    async def test_send_run_result_renders_plotly_json_as_photo(self):
        instance = _bot_instance()
        message = _message()
        instance._download_attachment = AsyncMock(return_value=b'{"data": []}')
        result = {
            "messages": [
                {"type": "human", "content": "Покажи график"},
                {
                    "type": "ai",
                    "content": "![graph](attachment:/bucket/chart.plotly.json)",
                },
            ],
        }

        with patch.object(
            instance,
            "_convert_plotly_attachment",
            return_value=(b"png-bytes", "chart.png", True),
        ):
            await instance._send_run_result(
                message=message,
                token="token",
                result=result,
                request_start=object(),
            )

        message.answer_photo.assert_awaited_once()
        message.answer_document.assert_not_awaited()
