"""Tests for the Telegram bot response extraction and message handling logic."""

import re
import pytest

from giga_agent.modules.telegram.bot import (
    _extract_ai_response,
    _extract_attachments,
    _scan_all_attachments,
    _strip_thinking,
    _split_message,
)


class TestStripThinking:
    def test_removes_thinking_block(self):
        text = "<thinking>\nSome reasoning\n</thinking>\n\nHello world"
        assert _strip_thinking(text) == "Hello world"

    def test_removes_multiline_thinking(self):
        text = "<thinking>\nLine 1\nLine 2\nLine 3\n</thinking>\n\nResult"
        assert _strip_thinking(text) == "Result"

    def test_returns_text_without_thinking(self):
        assert _strip_thinking("Just plain text") == "Just plain text"

    def test_empty_after_stripping(self):
        text = "<thinking>\nOnly thinking, no answer\n</thinking>"
        assert _strip_thinking(text) == ""

    def test_multiple_thinking_blocks(self):
        text = "<thinking>A</thinking> middle <thinking>B</thinking> end"
        assert _strip_thinking(text) == "middle  end"

    def test_preserves_other_tags(self):
        text = "<thinking>X</thinking>\n\n<b>Bold</b> text"
        assert _strip_thinking(text) == "<b>Bold</b> text"


class TestExtractAiResponse:
    def test_simple_ai_message(self):
        result = {
            "messages": [
                {"type": "human", "content": "Hello"},
                {"type": "ai", "content": "Hi there!"},
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "Hi there!"
        assert images == []

    def test_ai_message_with_thinking(self):
        result = {
            "messages": [
                {"type": "human", "content": "2+2?"},
                {"type": "ai", "content": "<thinking>\nPlan\n</thinking>\n\n4"},
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "4"

    def test_skips_ai_with_tool_calls(self):
        result = {
            "messages": [
                {"type": "human", "content": "calc"},
                {"type": "ai", "content": "", "tool_calls": [{"id": "1", "name": "python"}]},
                {"type": "tool", "content": "42", "tool_call_id": "1"},
                {"type": "ai", "content": "The answer is 42."},
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "The answer is 42."

    def test_takes_last_ai_message(self):
        result = {
            "messages": [
                {"type": "human", "content": "q"},
                {"type": "ai", "content": "First answer"},
                {"type": "human", "content": "q2"},
                {"type": "ai", "content": "Second answer"},
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "Second answer"

    def test_empty_messages(self):
        text, images = _extract_ai_response({"messages": []})
        assert text == ""
        assert images == []

    def test_no_messages_key(self):
        text, images = _extract_ai_response({})
        assert text == ""
        assert images == []

    def test_only_thinking_no_text(self):
        result = {
            "messages": [
                {"type": "human", "content": "q"},
                {"type": "ai", "content": "<thinking>\nJust thinking\n</thinking>"},
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == ""

    def test_list_content_with_text(self):
        result = {
            "messages": [
                {"type": "human", "content": "q"},
                {
                    "type": "ai",
                    "content": [
                        {"type": "text", "text": "Here is the answer"},
                    ],
                },
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "Here is the answer"

    def test_gigachat_full_flow(self):
        """Simulates a real GigaChat response with thinking + tool calls + final answer."""
        result = {
            "messages": [
                {"type": "human", "content": "15*7?"},
                {
                    "type": "ai",
                    "content": "<thinking>\nPlan: use code\n</thinking>\n",
                    "tool_calls": [{"id": "c1", "name": "python", "args": {"code": "15*7"}}],
                },
                {"type": "tool", "content": '{"result": 105}', "tool_call_id": "c1"},
                {
                    "type": "ai",
                    "content": "<thinking>\nGot result.\n</thinking>\n\nРезультат умножения 15 на 7 равен 105.",
                },
            ]
        }
        text, images = _extract_ai_response(result)
        assert text == "Результат умножения 15 на 7 равен 105."


class TestExtractAttachments:
    def test_single_attachment(self):
        text = "Вот график:\n\n![Парабола](attachment:/bucket/abc/img.png)"
        cleaned, paths = _extract_attachments(text)
        assert paths == ["/bucket/abc/img.png"]
        assert "attachment:" not in cleaned
        assert "Вот график:" in cleaned

    def test_multiple_attachments(self):
        text = (
            "![A](attachment:/bucket/a.png)\n"
            "Some text\n"
            "![B](attachment:/bucket/b.jpg)"
        )
        cleaned, paths = _extract_attachments(text)
        assert paths == ["/bucket/a.png", "/bucket/b.jpg"]
        assert "Some text" in cleaned

    def test_no_attachments(self):
        text = "Just plain text with no images"
        cleaned, paths = _extract_attachments(text)
        assert cleaned == text
        assert paths == []

    def test_real_world_example(self):
        text = (
            "Вот график простой параболы y = x^2:\n\n"
            "![Парабола](attachment:/bucket/68b6319e-7e55/img--abc.png)"
        )
        cleaned, paths = _extract_attachments(text)
        assert paths == ["/bucket/68b6319e-7e55/img--abc.png"]
        assert cleaned == "Вот график простой параболы y = x^2:"

    def test_preserves_normal_markdown_images(self):
        text = "![alt](https://example.com/img.png) and more"
        cleaned, paths = _extract_attachments(text)
        assert paths == []
        assert cleaned == text


class TestScanAllAttachments:
    def test_finds_in_tool_messages(self):
        result = {
            "messages": [
                {"type": "human", "content": "Нарисуй мем"},
                {"type": "ai", "content": "", "tool_calls": [{"id": "1", "name": "create_meme"}]},
                {
                    "type": "tool",
                    "content": "Мем создан: ![мем](attachment:/bucket/abc/meme.png)",
                    "tool_call_id": "1",
                },
                {"type": "ai", "content": "Вот ваш мем! Надеюсь понравится."},
            ]
        }
        paths = _scan_all_attachments(result)
        assert paths == ["/bucket/abc/meme.png"]

    def test_finds_in_additional_kwargs_attachments(self):
        result = {
            "messages": [
                {
                    "type": "tool",
                    "content": "done",
                    "additional_kwargs": {
                        "attachments": [{"sandbox_path": "/bucket/x/img.png"}]
                    },
                },
                {"type": "ai", "content": "Готово"},
            ]
        }
        paths = _scan_all_attachments(result)
        assert paths == ["/bucket/x/img.png"]

    def test_deduplicates(self):
        result = {
            "messages": [
                {"type": "tool", "content": "![a](attachment:/bucket/x.png)"},
                {"type": "ai", "content": "Вот: ![a](attachment:/bucket/x.png)"},
            ]
        }
        paths = _scan_all_attachments(result)
        assert paths == ["/bucket/x.png"]

    def test_empty(self):
        assert _scan_all_attachments({"messages": []}) == []


class TestSplitMessage:
    def test_short_message(self):
        assert _split_message("hello") == ["hello"]

    def test_exact_limit(self):
        text = "a" * 4096
        assert _split_message(text) == [text]

    def test_long_message_split_at_newline(self):
        part1 = "a" * 2000 + "\n"
        part2 = "b" * 2000
        text = part1 + part2
        parts = _split_message(text, max_len=2500)
        assert len(parts) == 2
        assert parts[0] == "a" * 2000
        assert parts[1] == "b" * 2000

    def test_empty_string(self):
        assert _split_message("") == [""]
