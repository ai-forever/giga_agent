import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from giga_agent.modules.telegram.services.media import TelegramMediaService
from giga_agent.modules.telegram.services.threads import TelegramThreadService


def _bot_row():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        bot_token="123456:telegram-test-token",
        bot_username="test_bot",
    )


class _FakeResponse:
    def __init__(self, status_code: int, *, json_data=None, content: bytes = b""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content

    def json(self):
        return self._json_data


class TelegramRuntimeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_service_recreates_expired_thread(self):
        bot_row = _bot_row()
        service = TelegramThreadService(bot_row=bot_row, user_email="owner@example.com")
        expired_thread = types.SimpleNamespace(
            updated_at=datetime.now(timezone.utc) - timedelta(days=2),
            langgraph_thread_id="thread-old",
        )
        repo = types.SimpleNamespace(
            get_thread=AsyncMock(return_value=expired_thread),
            delete_thread=AsyncMock(),
            touch_thread=AsyncMock(),
            create_thread=AsyncMock(),
        )
        client = types.SimpleNamespace(
            threads=types.SimpleNamespace(
                get=AsyncMock(),
                create=AsyncMock(return_value={"thread_id": "thread-new"}),
            )
        )

        thread_id = await service.get_or_create_thread(client, repo, chat_id=42)

        self.assertEqual(thread_id, "thread-new")
        repo.delete_thread.assert_awaited_once_with(expired_thread)
        client.threads.create.assert_awaited_once_with(
            metadata={"telegram_chat_id": "42"}
        )
        repo.create_thread.assert_awaited_once_with(bot_row.id, 42, "thread-new")

    async def test_thread_service_recreates_missing_langgraph_thread(self):
        bot_row = _bot_row()
        service = TelegramThreadService(bot_row=bot_row, user_email="owner@example.com")
        existing_thread = types.SimpleNamespace(
            updated_at=datetime.now(timezone.utc),
            langgraph_thread_id="thread-old",
        )
        repo = types.SimpleNamespace(
            get_thread=AsyncMock(return_value=existing_thread),
            delete_thread=AsyncMock(),
            touch_thread=AsyncMock(),
            create_thread=AsyncMock(),
        )
        client = types.SimpleNamespace(
            threads=types.SimpleNamespace(
                get=AsyncMock(side_effect=RuntimeError("missing")),
                create=AsyncMock(return_value={"thread_id": "thread-new"}),
            )
        )

        thread_id = await service.get_or_create_thread(client, repo, chat_id=99)

        self.assertEqual(thread_id, "thread-new")
        repo.delete_thread.assert_awaited_once_with(existing_thread)
        repo.touch_thread.assert_not_awaited()
        repo.create_thread.assert_awaited_once_with(bot_row.id, 99, "thread-new")

    async def test_media_service_download_attachment_uses_files_api_fallback(self):
        bot_row = _bot_row()
        bot = types.SimpleNamespace()
        service = TelegramMediaService(bot=bot, bot_row=bot_row)

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                params = kwargs.get("params") or {}
                if url.endswith("/files/content/by-path") and params.get("path") == "/bucket/missing/12345--chart.png":
                    return _FakeResponse(404)
                if url.endswith("/files"):
                    return _FakeResponse(
                        200,
                        json_data=[
                            {
                                "sandbox_path": "/bucket/fallback/12345--chart.png",
                            }
                        ],
                    )
                if url.endswith("/files/content/by-path") and params.get("path") == "/bucket/fallback/12345--chart.png":
                    return _FakeResponse(200, content=b"image-bytes")
                raise AssertionError(f"Unexpected request: {url} {params}")

        with patch(
            "giga_agent.modules.telegram.services.media.httpx.AsyncClient",
            return_value=_FakeAsyncClient(),
        ):
            content = await service.download_attachment(
                "token",
                "/bucket/missing/12345--chart.png",
            )

        self.assertEqual(content, b"image-bytes")

    async def test_media_service_find_recent_image_files_filters_recent_images(self):
        bot_row = _bot_row()
        bot = types.SimpleNamespace()
        service = TelegramMediaService(bot=bot, bot_row=bot_row)
        now = datetime.now(timezone.utc)

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                self._kwargs = kwargs
                return _FakeResponse(
                    200,
                    json_data=[
                        {
                            "file_type": "image",
                            "created_at": now.isoformat(),
                            "sandbox_path": "/bucket/recent.png",
                        },
                        {
                            "file_type": "document",
                            "created_at": now.isoformat(),
                            "sandbox_path": "/bucket/document.pdf",
                        },
                        {
                            "file_type": "image",
                            "created_at": (now - timedelta(days=3)).isoformat(),
                            "sandbox_path": "/bucket/old.png",
                        },
                    ],
                )

        with patch(
            "giga_agent.modules.telegram.services.media.httpx.AsyncClient",
            return_value=_FakeAsyncClient(),
        ):
            paths = await service.find_recent_image_files(
                "token",
                since=now - timedelta(hours=1),
            )

        self.assertEqual(paths, ["/bucket/recent.png"])
