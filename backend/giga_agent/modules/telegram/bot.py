"""Telegram bot runner – starts/stops aiogram bots per user."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from langgraph_sdk import get_client

from giga_agent.conf import get_settings, GIGA_AGENT_PREFIX_API
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.auth.security import create_access_token
from giga_agent.modules.telegram.models import (
    TelegramBot as TelegramBotModel,
    TelegramBotRepository,
)

logger = get_logger(__name__)

ASSISTANT_ID = "giga_agent"
THREAD_TTL_SECONDS = 24 * 60 * 60


def _langgraph_url() -> str:
    settings = get_settings()
    return settings.giga_agent_langgraph_api_url or "http://localhost:8000"


def _agent_api_base() -> str:
    """Base URL for the agent's own FastAPI routes (mounted at /api)."""
    return f"{_langgraph_url()}/api{GIGA_AGENT_PREFIX_API}"


def _make_token(user_id: uuid.UUID, email: str) -> str:
    return create_access_token(
        data={"sub": email, "user_id": str(user_id)},
    )


_ATTACHMENT_RE = re.compile(
    r"!\[([^\]]*)\]\(attachment:(/?[^)]+)\)"
)


def _strip_thinking(text: str) -> str:
    return re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()


def _extract_attachments(text: str) -> tuple[str, list[str]]:
    paths: list[str] = []
    for match in _ATTACHMENT_RE.finditer(text):
        paths.append(match.group(2))
    cleaned = _ATTACHMENT_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, paths


def _scan_current_turn_attachments(
    result: dict, prev_message_count: int = 0,
) -> list[str]:
    """Scan only NEW messages (after prev_message_count) for attachment paths.

    This prevents resending attachments from earlier turns.
    """
    paths: list[str] = []
    seen: set[str] = set()
    messages = result.get("messages") or []
    for msg in messages[prev_message_count:]:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            for match in _ATTACHMENT_RE.finditer(content):
                p = match.group(2)
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        ak = msg.get("additional_kwargs") or {}
        for att in ak.get("attachments") or []:
            if isinstance(att, dict) and att.get("sandbox_path"):
                p = att["sandbox_path"]
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
    return paths


def _extract_ai_response(result: dict) -> tuple[str, list[str]]:
    messages = result.get("messages") or []
    text_parts: list[str] = []
    image_urls: list[str] = []

    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("type") or msg.get("role", "")
        if role != "ai":
            continue
        if msg.get("tool_calls"):
            continue

        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            cleaned = _strip_thinking(content)
            if cleaned:
                text_parts.append(cleaned)
            break
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        text_parts.append(block["text"].strip())
                    elif block.get("type") == "image_url":
                        url = block.get("image_url", {})
                        if isinstance(url, str):
                            image_urls.append(url)
                        elif isinstance(url, dict) and url.get("url"):
                            image_urls.append(url["url"])
                elif isinstance(block, str) and block.strip():
                    text_parts.append(block.strip())
            if text_parts:
                break

    return "\n\n".join(text_parts), image_urls


class _BotInstance:

    def __init__(self, bot_row: TelegramBotModel, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email
        self.bot = Bot(token=bot_row.bot_token)
        self.dp = Dispatcher()
        self._task: asyncio.Task | None = None
        self._setup_handlers()

    def _setup_handlers(self):
        @self.dp.message(Command("new"))
        async def _on_new(message: tg_types.Message):
            await self._handle_new(message)

        @self.dp.message(Command("start"))
        async def _on_start(message: tg_types.Message):
            await message.answer(
                "Привет! Я GigaAgent — универсальный AI-агент.\n\n"
                "Просто напишите мне сообщение, и я отвечу.\n"
                "Можете отправлять фото, документы и голосовые.\n"
                "/new — начать новый диалог (сбросить контекст)"
            )

        @self.dp.message()
        async def _on_message(message: tg_types.Message):
            text = message.text or message.caption or ""
            has_file = bool(
                message.photo or message.document
                or message.voice or message.audio
                or message.video or message.video_note
                or message.sticker
            )
            if not text and not has_file:
                return
            await self._handle_message(message)

    async def _handle_new(self, message: tg_types.Message):
        chat_id = message.chat.id
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            await self._reset_thread(repo, chat_id)
        await message.answer("🔄 Контекст сброшен. Начнём новый диалог!")

    async def _get_or_create_thread(
        self, client: Any, repo: TelegramBotRepository, chat_id: int
    ) -> str:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            expired = False
            if thread_row.updated_at:
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc) - thread_row.updated_at.replace(tzinfo=timezone.utc)).total_seconds()
                if age > THREAD_TTL_SECONDS:
                    expired = True
            if expired:
                logger.info("Thread for chat %s expired (age=%ds), creating new", chat_id, age)
                await repo.delete_thread(thread_row)
            else:
                await repo.touch_thread(thread_row)
                return thread_row.langgraph_thread_id

        thread = await client.threads.create(
            metadata={"telegram_chat_id": str(chat_id)},
        )
        thread_id = thread["thread_id"]
        await repo.create_thread(self.bot_row.id, chat_id, thread_id)
        return thread_id

    async def _reset_thread(
        self, repo: TelegramBotRepository, chat_id: int
    ) -> None:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            await repo.delete_thread(thread_row)

    async def _upload_tg_file(
        self, token: str, file_id: str, file_name: str, thread_id: str,
    ) -> dict | None:
        """Download file from Telegram and upload to agent file API."""
        import httpx
        try:
            tg_file = await self.bot.get_file(file_id)
            bio = await self.bot.download_file(tg_file.file_path)
            if bio is None:
                logger.warning("Telegram returned None for file %s", file_id)
                return None
            data = bio.read() if hasattr(bio, "read") else bytes(bio)
            logger.info("Downloaded TG file %s: %d bytes", file_name, len(data))

            url = f"{_agent_api_base()}/files/upload"
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    data={"thread_id": thread_id},
                    files={"file": (file_name, data)},
                )
                if resp.status_code in (200, 201):
                    result = resp.json()
                    logger.info("Uploaded file %s -> %s", file_name, result.get("sandbox_path"))
                    return result
                logger.warning("File upload failed: %d %s", resp.status_code, resp.text[:300])
        except Exception:
            logger.exception("Failed to upload Telegram file %s", file_name)
        return None

    async def _handle_message(self, message: tg_types.Message):
        chat_id = message.chat.id
        text = message.text or message.caption or ""
        user_id = self.bot_row.user_id

        logger.info("Telegram message from chat %s: %s", chat_id, text[:100])

        try:
            token = _make_token(user_id, self.user_email)
            client = get_client(
                url=_langgraph_url(),
                headers={"Authorization": f"Bearer {token}"},
            )

            session_factory = await get_session_factory()
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                thread_id = await self._get_or_create_thread(client, repo, chat_id)

            await message.chat.do("typing")

            uploaded_files: list[dict] = []
            if message.photo:
                photo = message.photo[-1]
                f = await self._upload_tg_file(token, photo.file_id, "photo.jpg", thread_id)
                if f:
                    uploaded_files.append(f)
            if message.document:
                fname = message.document.file_name or "document"
                f = await self._upload_tg_file(token, message.document.file_id, fname, thread_id)
                if f:
                    uploaded_files.append(f)
            if message.voice:
                f = await self._upload_tg_file(token, message.voice.file_id, "voice.ogg", thread_id)
                if f:
                    uploaded_files.append(f)
            if message.audio:
                fname = message.audio.file_name or "audio.mp3"
                f = await self._upload_tg_file(token, message.audio.file_id, fname, thread_id)
                if f:
                    uploaded_files.append(f)
            if message.video:
                fname = message.video.file_name or "video.mp4"
                f = await self._upload_tg_file(token, message.video.file_id, fname, thread_id)
                if f:
                    uploaded_files.append(f)

            file_data = [
                {"path": f["sandbox_path"], "original_name": f.get("original_name", ""), "file_type": f.get("file_type", "other"), "size": f.get("size", 0)}
                for f in uploaded_files
            ]
            if file_data:
                logger.info("Files for agent: %s", [fd["path"] for fd in file_data])

            content = text or ("Прикреплён файл: " + ", ".join(fd.get("original_name", fd["path"]) for fd in file_data) if file_data else "")
            human_msg: dict[str, Any] = {"role": "human", "content": content}
            if file_data:
                human_msg["additional_kwargs"] = {
                    "user_input": content,
                    "files": file_data,
                }

            prev_state = await client.threads.get_state(thread_id)
            prev_messages = (prev_state.get("values") or {}).get("messages") or []
            prev_message_count = len(prev_messages)

            result = await client.runs.wait(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                input={"messages": [human_msg]},
            )

            for _ in range(10):
                if not isinstance(result, dict):
                    break
                msgs = result.get("messages", [])
                last_ai = None
                for m in reversed(msgs):
                    if isinstance(m, dict) and m.get("type") == "ai":
                        last_ai = m
                        break
                if last_ai and last_ai.get("tool_calls"):
                    logger.info("Auto-approving tool calls for chat %s", chat_id)
                    await message.chat.do("typing")
                    result = await client.runs.wait(
                        thread_id=thread_id,
                        assistant_id=ASSISTANT_ID,
                        input=None,
                        command={"resume": {"type": "approve"}},
                    )
                else:
                    break

            if not isinstance(result, dict) or not result.get("messages"):
                logger.warning("Empty result for chat %s: %s", chat_id, str(result)[:500])
                async with session_factory() as session:
                    repo = TelegramBotRepository(session)
                    await self._reset_thread(repo, chat_id)
                await message.answer("⚠️ Агент не вернул ответ. Попробуйте ещё раз.")
                return

            response_text, image_urls = _extract_ai_response(result)
            response_text, attachment_paths = _extract_attachments(response_text)

            if not attachment_paths:
                attachment_paths = _scan_current_turn_attachments(
                    result, prev_message_count,
                )

            logger.info(
                "Response for chat %s: text=%d chars, images=%d, attachments=%d",
                chat_id, len(response_text), len(image_urls), len(attachment_paths),
            )

            sent_any = False

            for path in attachment_paths[:10]:
                try:
                    file_bytes = await self._download_attachment(token, path)
                    if file_bytes:
                        fname = path.rsplit("/", 1)[-1] if "/" in path else path
                        inp = BufferedInputFile(file_bytes, filename=fname)
                        lower = fname.lower()
                        if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                            await message.answer_photo(inp)
                        else:
                            await message.answer_document(inp)
                        sent_any = True
                except Exception:
                    logger.warning("Failed to send attachment %s", path[:80])

            for url in image_urls[:5]:
                try:
                    await self._send_image(message, url)
                    sent_any = True
                except Exception:
                    logger.warning("Failed to send image to Telegram")

            if response_text:
                for chunk in _split_message(response_text):
                    await message.answer(chunk)
                sent_any = True

            if not sent_any:
                await message.answer("✅ Задача выполнена.")

        except Exception as exc:
            logger.exception("Error handling Telegram message for user %s", user_id)
            error_str = str(exc)
            if "tool_call" in error_str or "function call" in error_str:
                try:
                    async with (await get_session_factory())() as session:
                        repo = TelegramBotRepository(session)
                        await self._reset_thread(repo, chat_id)
                except Exception:
                    pass
                try:
                    await message.answer("⚠️ Контекст повреждён, сброшен. Повторите сообщение.")
                except Exception:
                    pass
            else:
                try:
                    await message.answer("⚠️ Произошла ошибка при обработке сообщения.")
                except Exception:
                    pass

    async def _download_attachment(self, token: str, path: str) -> bytes | None:
        import httpx
        url = f"{_agent_api_base()}/files/content/by-path"
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                url,
                params={"path": path},
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.content
            logger.warning("Failed to download %s: %d", path[:80], resp.status_code)
            return None

    async def _send_image(self, message: tg_types.Message, url: str):
        if url.startswith("http"):
            await message.answer_photo(url)
        elif url.startswith("data:image"):
            import base64
            _, b64data = url.split(",", 1)
            photo_bytes = base64.b64decode(b64data)
            await message.answer_photo(
                BufferedInputFile(photo_bytes, filename="image.png")
            )

    async def start(self):
        logger.info(
            "Starting Telegram bot %s for user %s",
            self.bot_row.bot_username or self.bot_row.id,
            self.bot_row.user_id,
        )
        await self.bot.delete_webhook(drop_pending_updates=True)
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            await self.dp.start_polling(self.bot, handle_signals=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Telegram bot polling failed for %s", self.bot_row.id)

    async def stop(self):
        logger.info("Stopping Telegram bot %s", self.bot_row.id)
        if self._task and not self._task.done():
            await self.dp.stop_polling()
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.bot.session.close()


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return parts


class TelegramBotManager:

    def __init__(self):
        self._bots: dict[uuid.UUID, _BotInstance] = {}

    async def start_all(self):
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            bots = await repo.get_all_enabled()
            for bot_row in bots:
                await self._start_bot(bot_row, session)

    async def _start_bot(self, bot_row: TelegramBotModel, session: Any):
        if bot_row.id in self._bots:
            return

        from giga_agent.models.users import UserRepository
        user = await UserRepository(session).get_by_id(bot_row.user_id, use_cache=False)
        if user is None:
            logger.warning("User %s not found for bot %s", bot_row.user_id, bot_row.id)
            return

        try:
            instance = _BotInstance(bot_row, user.email)
            bot_info = await instance.bot.get_me()
            if bot_row.bot_username != bot_info.username:
                bot_row.bot_username = bot_info.username
                await session.commit()
            self._bots[bot_row.id] = instance
            await instance.start()
        except Exception:
            logger.exception("Failed to start Telegram bot %s", bot_row.id)

    async def start_bot(self, bot_id: uuid.UUID):
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            bot_row = await repo.get_by_id(bot_id)
            if bot_row and bot_row.is_enabled:
                await self._start_bot(bot_row, session)

    async def stop_bot(self, bot_id: uuid.UUID):
        instance = self._bots.pop(bot_id, None)
        if instance:
            await instance.stop()

    async def restart_bot(self, bot_id: uuid.UUID):
        await self.stop_bot(bot_id)
        await self.start_bot(bot_id)

    async def stop_all(self):
        for bot_id in list(self._bots.keys()):
            await self.stop_bot(bot_id)

    def is_running(self, bot_id: uuid.UUID) -> bool:
        return bot_id in self._bots


_manager: TelegramBotManager | None = None


def get_bot_manager() -> TelegramBotManager:
    global _manager
    if _manager is None:
        _manager = TelegramBotManager()
    return _manager
