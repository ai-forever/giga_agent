import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from giga_agent.channels.telegram.services.media import TelegramMediaService
from giga_agent.channels.telegram.services.threads import TelegramThreadService


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
            metadata={
                "telegram_chat_id": "42",
                "channel": "telegram",
                "is_channel": True,
                "auto_approve": True,
            }
        )
        repo.create_thread.assert_awaited_once_with(
            bot_id=bot_row.id,
            external_chat_id="42",
            external_user_id=None,
            langgraph_thread_id="thread-new",
        )

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
        repo.create_thread.assert_awaited_once_with(
            bot_id=bot_row.id,
            external_chat_id="99",
            external_user_id=None,
            langgraph_thread_id="thread-new",
        )

    async def test_reset_thread_stops_active_langgraph_runs_by_default(self):
        bot_row = _bot_row()
        service = TelegramThreadService(bot_row=bot_row, user_email="owner@example.com")
        existing_thread = types.SimpleNamespace(langgraph_thread_id="thread-old")
        repo = types.SimpleNamespace(
            get_thread=AsyncMock(return_value=existing_thread),
            delete_thread=AsyncMock(),
        )
        client = types.SimpleNamespace(
            runs=types.SimpleNamespace(
                list=AsyncMock(
                    side_effect=[
                        [{"run_id": "run-1"}, {"run_id": "run-2"}],
                        [{"run_id": "run-3"}],
                    ]
                ),
                cancel=AsyncMock(),
            )
        )
        service.create_token = lambda: "token"
        service.create_client = lambda token: client

        with patch(
            "giga_agent.channels.telegram.services.threads.asyncio.create_task"
        ) as create_task:
            await service.reset_thread(repo, chat_id=42)

        create_task.assert_called_once()
        await create_task.call_args.args[0]

        client.runs.list.assert_any_await("thread-old", limit=100, status="running")
        client.runs.list.assert_any_await("thread-old", limit=100, status="pending")
        client.runs.cancel.assert_any_await("thread-old", "run-1", action="interrupt")
        client.runs.cancel.assert_any_await("thread-old", "run-2", action="interrupt")
        client.runs.cancel.assert_any_await("thread-old", "run-3", action="interrupt")
        self.assertEqual(client.runs.cancel.await_count, 3)
        repo.delete_thread.assert_awaited_once_with(existing_thread)

    async def test_reset_thread_skips_stopping_langgraph_runs_when_disabled(self):
        bot_row = _bot_row()
        service = TelegramThreadService(bot_row=bot_row, user_email="owner@example.com")
        existing_thread = types.SimpleNamespace(langgraph_thread_id="thread-old")
        repo = types.SimpleNamespace(
            get_thread=AsyncMock(return_value=existing_thread),
            delete_thread=AsyncMock(),
        )
        service.create_token = lambda: "token"
        service.create_client = AsyncMock()

        await service.reset_thread(repo, chat_id=42, stop_thread=False)

        service.create_client.assert_not_awaited()
        repo.delete_thread.assert_awaited_once_with(existing_thread)

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
                if (
                    url.endswith("/files/content/by-path")
                    and params.get("path") == "/bucket/missing/12345--chart.png"
                ):
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
                if (
                    url.endswith("/files/content/by-path")
                    and params.get("path") == "/bucket/fallback/12345--chart.png"
                ):
                    return _FakeResponse(200, content=b"image-bytes")
                raise AssertionError(f"Unexpected request: {url} {params}")

        with patch(
            "giga_agent.channels.telegram.services.media.httpx.AsyncClient",
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
            "giga_agent.channels.telegram.services.media.httpx.AsyncClient",
            return_value=_FakeAsyncClient(),
        ):
            paths = await service.find_recent_image_files(
                "token",
                since=now - timedelta(hours=1),
            )

        self.assertEqual(paths, ["/bucket/recent.png"])


_SANDBOX_HEX = "ab" * 16  # 32 hex chars


class InjectSandboxAccessTokensTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, bot_row):
        bot = types.SimpleNamespace()
        return TelegramMediaService(bot=bot, bot_row=bot_row)

    @staticmethod
    def _session_factory():
        class _Ctx:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False

        return AsyncMock(return_value=lambda: _Ctx())

    def _patches(self, *, settings, owner_id):
        repo = types.SimpleNamespace(
            get_owner_id_by_sandbox_cached=AsyncMock(return_value=owner_id),
        )
        return (
            patch(
                "giga_agent.channels.telegram.services.media.get_settings",
                return_value=settings,
            ),
            patch(
                "giga_agent.channels.telegram.services.media.get_session_factory",
                self._session_factory(),
            ),
            patch(
                "giga_agent.channels.telegram.services.media.SandboxRepository",
                return_value=repo,
            ),
            patch(
                "giga_agent.channels.telegram.services.media.mint_sandbox_access_token",
                AsyncMock(return_value="TESTTOKEN"),
            ),
        )

    async def test_redirect_link_rewritten_to_direct_url_with_token(self):
        bot_row = _bot_row()
        service = self._service(bot_row)
        settings = types.SimpleNamespace(
            giga_agent_public_base_domain=None,
            giga_agent_sandbox_port_redirect_base="gigapp.ru",
        )
        text = (
            "Открыл порт: "
            f"https://app.example.com/api/v1/sandbox-redirect/{_SANDBOX_HEX}/8501"
        )
        p1, p2, p3, p4 = self._patches(settings=settings, owner_id=bot_row.user_id)
        with p1, p2, p3, p4:
            result = await service.inject_sandbox_access_tokens(text)

        self.assertIn(
            f"https://8501-sandbox-{_SANDBOX_HEX}.gigapp.ru/?__sbx=TESTTOKEN",
            result,
        )
        self.assertNotIn("/sandbox-redirect/", result)

    async def test_redirect_link_foreign_owner_untouched(self):
        bot_row = _bot_row()
        service = self._service(bot_row)
        settings = types.SimpleNamespace(
            giga_agent_public_base_domain=None,
            giga_agent_sandbox_port_redirect_base="gigapp.ru",
        )
        url = f"https://app.example.com/api/v1/sandbox-redirect/{_SANDBOX_HEX}/8501"
        # Different owner → no token, link left as-is.
        p1, p2, p3, p4 = self._patches(settings=settings, owner_id=uuid.uuid4())
        with p1, p2, p3, p4:
            result = await service.inject_sandbox_access_tokens(url)

        self.assertEqual(result, url)

    async def test_direct_url_still_gets_token(self):
        bot_row = _bot_row()
        service = self._service(bot_row)
        settings = types.SimpleNamespace(
            giga_agent_public_base_domain="gigapp.ru",
            giga_agent_sandbox_port_redirect_base=None,
        )
        url = f"https://8501-sandbox-{_SANDBOX_HEX}.gigapp.ru/"
        p1, p2, p3, p4 = self._patches(settings=settings, owner_id=bot_row.user_id)
        with p1, p2, p3, p4:
            result = await service.inject_sandbox_access_tokens(url)

        self.assertEqual(
            result,
            f"https://8501-sandbox-{_SANDBOX_HEX}.gigapp.ru/?__sbx=TESTTOKEN",
        )
