"""Telegram bot runner – starts/stops aiogram bots per user."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BufferedInputFile,
)
from langgraph_sdk import get_client

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.modules.telegram.message_tool import (
    TelegramMessageToolPayload,
    build_telegram_message_tool_schema,
    parse_telegram_message_tool_payload,
)
from giga_agent.modules.telegram.models import (
    TelegramBot as TelegramBotModel,
    TelegramBotRepository,
)
from giga_agent.modules.telegram.utils import (
    _agent_api_base,
    _build_message_tool_result_parts,
    _describe_uploaded_files,
    _extract_ai_response,
    _extract_attachments,
    _find_last_human_index,
    _find_pending_message_tool_calls,
    _langgraph_url,
    _make_token,
    _md_to_tg_markdown_v2,
    _plotly_json_to_png_bytes,
    _scan_current_turn_attachments,
    _split_message,
)

logger = get_logger(__name__)

ASSISTANT_ID = "giga_agent"
THREAD_TTL_SECONDS = 24 * 60 * 60
_MESSAGE_TOOL_CALLBACK_PREFIX = "ga_msg:"
_SUPPORTED_CHAT_TYPES = {"private", "group", "supergroup"}
_GROUP_CHAT_TYPES = {"group", "supergroup"}


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

        @self.dp.message(Command("message"))
        async def _on_message_command(message: tg_types.Message):
            await self._handle_message_command(message)

        @self.dp.message(Command("start"))
        async def _on_start(message: tg_types.Message):
            if not await self._ensure_supported_chat(message):
                return
            await self._register_contact(message)
            await message.answer(
                "Привет! Я GigaAgent — универсальный AI-агент.\n\n"
                "Просто напишите мне сообщение, и я отвечу.\n"
                "Можете отправлять фото, документы и голосовые.\n"
                "/new — начать новый диалог (сбросить контекст)"
            )

        @self.dp.callback_query()
        async def _on_callback_query(callback: tg_types.CallbackQuery):
            await self._handle_callback_query(callback)

        @self.dp.message()
        async def _on_message(message: tg_types.Message):
            text = message.text or message.caption or ""
            has_file = bool(
                message.photo
                or message.document
                or message.voice
                or message.audio
                or message.video
                or message.video_note
                or message.sticker
            )
            if not text and not has_file:
                return
            if not self._should_process_message(message):
                return
            await self._handle_message(message)

    def _build_contact_payload(self, message: tg_types.Message) -> dict[str, Any]:
        chat = message.chat
        chat_type = getattr(chat, "type", None)
        chat_title = getattr(chat, "title", None)
        chat_username = getattr(chat, "username", None)

        if chat_type == "private":
            tg_user = message.from_user
            return {
                "chat_type": chat_type,
                "chat_title": None,
                "username": (
                    tg_user.username
                    if tg_user and tg_user.username is not None
                    else chat_username
                ),
                "first_name": (
                    tg_user.first_name
                    if tg_user and tg_user.first_name is not None
                    else getattr(chat, "first_name", None)
                ),
                "last_name": (
                    tg_user.last_name
                    if tg_user and tg_user.last_name is not None
                    else getattr(chat, "last_name", None)
                ),
            }

        return {
            "chat_type": chat_type,
            "chat_title": chat_title,
            "username": chat_username,
            "first_name": None,
            "last_name": None,
        }

    async def _ensure_supported_chat(
        self,
        message: tg_types.Message,
        *,
        callback: tg_types.CallbackQuery | None = None,
    ) -> bool:
        chat_type = getattr(message.chat, "type", None)
        if chat_type in _SUPPORTED_CHAT_TYPES:
            return True

        if callback is not None:
            await callback.answer("Этот тип чата не поддерживается", show_alert=True)
        else:
            await message.answer(
                "Этот тип чата пока не поддерживается. Используйте личный чат, группу или супергруппу."
            )
        return False

    def _should_process_message(self, message: tg_types.Message) -> bool:
        chat_type = getattr(message.chat, "type", None)
        if chat_type == "private":
            return True
        if chat_type not in _GROUP_CHAT_TYPES:
            return False

        reply_message = getattr(message, "reply_to_message", None)
        reply_user = getattr(reply_message, "from_user", None)
        if reply_user is not None and getattr(reply_user, "is_bot", False):
            reply_username = getattr(reply_user, "username", None)
            bot_username = self.bot_row.bot_username
            if bot_username and reply_username:
                if reply_username.lower() == bot_username.lower():
                    return True
            bot_id = getattr(self.bot, "id", None)
            if bot_id is not None and getattr(reply_user, "id", None) == bot_id:
                return True

        text = message.text or message.caption or ""
        entities = list(getattr(message, "entities", None) or []) + list(
            getattr(message, "caption_entities", None) or []
        )
        username = (self.bot_row.bot_username or "").lower()
        if not username:
            return False

        for entity in entities:
            entity_type = getattr(entity, "type", None)
            if entity_type == "mention":
                offset = getattr(entity, "offset", 0)
                length = getattr(entity, "length", 0)
                mention = text[offset : offset + length].lower()
                if mention == f"@{username}":
                    return True
            if entity_type == "text_mention":
                entity_user = getattr(entity, "user", None)
                if entity_user is None:
                    continue
                entity_user_username = getattr(entity_user, "username", None)
                if entity_user_username and entity_user_username.lower() == username:
                    return True
                bot_id = getattr(self.bot, "id", None)
                if bot_id is not None and getattr(entity_user, "id", None) == bot_id:
                    return True

        return False

    def _strip_bot_mentions(self, text: str) -> str:
        username = self.bot_row.bot_username
        if not text or not username:
            return text

        without_mentions = re.sub(
            rf"(?i)(?<!\w)@{re.escape(username)}\b",
            "",
            text,
        )
        without_mentions = re.sub(r"[ \t]{2,}", " ", without_mentions)
        without_mentions = re.sub(r"\n{3,}", "\n\n", without_mentions)
        return without_mentions.strip()

    def _strip_command_prefix(self, text: str, command: str) -> str:
        if not text:
            return text

        bot_username = re.escape(self.bot_row.bot_username or "")
        command_pattern = rf"^/{re.escape(command)}(?:@{bot_username})?(?:\s+|$)"
        stripped = re.sub(command_pattern, "", text, count=1, flags=re.IGNORECASE)
        stripped = re.sub(r"^[ \t]+", "", stripped)
        return stripped

    def _build_reply_kwargs(self, reply_to_message_id: int | None) -> dict[str, Any]:
        if reply_to_message_id is None:
            return {}
        return {
            "reply_parameters": tg_types.ReplyParameters(
                message_id=reply_to_message_id
            )
        }

    async def _register_contact(self, message: tg_types.Message) -> None:
        """Upsert the current Telegram chat as a contact."""
        try:
            contact_payload = self._build_contact_payload(message)
            session_factory = await get_session_factory()
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                await repo.upsert_contact(
                    bot_id=self.bot_row.id,
                    telegram_chat_id=message.chat.id,
                    **contact_payload,
                )
        except Exception:
            logger.warning("Failed to register contact for chat %s", message.chat.id)

    async def _handle_new(self, message: tg_types.Message):
        if not await self._ensure_supported_chat(message):
            return
        chat_id = message.from_user.id
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            await self._reset_thread(repo, chat_id)
        await message.answer(
            "🔄 Контекст сброшен. Начнём новый диалог!",
            reply_markup=tg_types.ReplyKeyboardRemove(),
        )

    async def _handle_message_command(self, message: tg_types.Message) -> None:
        if not await self._ensure_supported_chat(message):
            return

        command_text = self._strip_command_prefix(message.text or message.caption or "", "message")
        has_file = bool(
            message.photo
            or message.document
            or message.voice
            or message.audio
            or message.video
            or message.video_note
            or message.sticker
        )
        if not command_text and not has_file:
            await message.answer(
                "После /message нужен текст или вложение для обработки."
            )
            return

        await self._handle_message(
            message,
            force_process=True,
            text_override=command_text,
        )

    async def _get_or_create_thread(
        self, client: Any, repo: TelegramBotRepository, chat_id: int
    ) -> str:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            expired = False
            if thread_row.updated_at:
                from datetime import datetime, timezone

                age = (
                    datetime.now(timezone.utc)
                    - thread_row.updated_at.replace(tzinfo=timezone.utc)
                ).total_seconds()
                if age > THREAD_TTL_SECONDS:
                    expired = True
            if expired:
                logger.info(
                    "Thread for chat %s expired (age=%ds), creating new", chat_id, age
                )
                await repo.delete_thread(thread_row)
            else:
                # Verify thread still exists in LangGraph (in-memory store resets on restart)
                try:
                    await client.threads.get(thread_row.langgraph_thread_id)
                    await repo.touch_thread(thread_row)
                    return thread_row.langgraph_thread_id
                except Exception:
                    logger.info(
                        "Thread %s no longer exists in LangGraph, recreating",
                        thread_row.langgraph_thread_id,
                    )
                    await repo.delete_thread(thread_row)

        thread = await client.threads.create(
            metadata={"telegram_chat_id": str(chat_id)},
        )
        thread_id = thread["thread_id"]
        await repo.create_thread(self.bot_row.id, chat_id, thread_id)
        return thread_id

    async def _reset_thread(self, repo: TelegramBotRepository, chat_id: int) -> None:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            await repo.delete_thread(thread_row)

    async def _upload_tg_file(
        self,
        token: str,
        file_id: str,
        file_name: str,
        thread_id: str,
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
                    logger.info(
                        "Uploaded file %s -> %s", file_name, result.get("sandbox_path")
                    )
                    return result
                logger.warning(
                    "File upload failed: %d %s", resp.status_code, resp.text[:300]
                )
        except Exception:
            logger.exception("Failed to upload Telegram file %s", file_name)
        return None

    async def _collect_incoming_files(
        self,
        message: tg_types.Message,
        token: str,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        uploaded_files: list[dict[str, Any]] = []
        if message.photo:
            photo = message.photo[-1]
            f = await self._upload_tg_file(token, photo.file_id, "photo.jpg", thread_id)
            if f:
                uploaded_files.append(f)
        if message.document:
            fname = message.document.file_name or "document"
            f = await self._upload_tg_file(
                token, message.document.file_id, fname, thread_id
            )
            if f:
                uploaded_files.append(f)
        if message.voice:
            f = await self._upload_tg_file(
                token, message.voice.file_id, "voice.ogg", thread_id
            )
            if f:
                uploaded_files.append(f)
        if message.audio:
            fname = message.audio.file_name or "audio.mp3"
            f = await self._upload_tg_file(
                token, message.audio.file_id, fname, thread_id
            )
            if f:
                uploaded_files.append(f)
        if message.video:
            fname = message.video.file_name or "video.mp4"
            f = await self._upload_tg_file(
                token, message.video.file_id, fname, thread_id
            )
            if f:
                uploaded_files.append(f)
        return [
            {
                "path": f["sandbox_path"],
                "original_name": f.get("original_name", ""),
                "file_type": f.get("file_type", "other"),
                "size": f.get("size", 0),
            }
            for f in uploaded_files
        ]

    def _format_message_author(self, message: tg_types.Message) -> tuple[str, str]:
        author = getattr(message, "from_user", None) or getattr(
            message, "sender_chat", None
        )
        username = getattr(author, "username", None)
        username_value = f"@{username}" if username else "unknown"
        name_parts = [
            getattr(author, "first_name", None),
            getattr(author, "last_name", None),
        ]
        full_name = " ".join(part for part in name_parts if part).strip()
        if not full_name:
            full_name = getattr(author, "title", None) or "Unknown"
        return username_value, full_name

    def _build_message_context(
        self,
        *,
        label: str,
        message: tg_types.Message,
        text: str,
        files: list[dict[str, Any]],
    ) -> str:
        username, full_name = self._format_message_author(message)
        lines = [
            f"{label}:",
            f"Ник: {username}",
            f"Имя: {full_name}",
            "Текст сообщения:",
            text or "[empty]",
        ]
        if files:
            lines.extend(
                [
                    "Файлы:",
                    _describe_uploaded_files(files),
                ]
            )
        return "\n".join(lines)

    async def _load_collections_payload(self) -> list[dict[str, Any]]:
        collections_payload: list[dict[str, Any]] = []
        try:
            async with (await get_session_factory())() as session:
                rows = await RagCollectionsRepository(session).list_by_owner(
                    self.bot_row.user_id,
                )
                collections_payload = [
                    {"uuid": str(r.id), "name": r.name, "metadata": r.metadata_ or {}}
                    for r in rows
                ]
        except Exception:
            logger.warning(
                "Failed to load RAG collections for user %s",
                self.bot_row.user_id,
            )
        return collections_payload

    async def _get_pending_message_tool_call(
        self,
        client: Any,
        thread_id: str,
    ) -> dict[str, Any] | None:
        pending_tool_calls = await self._get_pending_message_tool_calls(client, thread_id)
        return pending_tool_calls[-1] if pending_tool_calls else None

    async def _get_pending_message_tool_calls(
        self,
        client: Any,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        try:
            thread_state = await client.threads.get_state(thread_id)
        except Exception:
            logger.debug(
                "Failed to fetch thread state for %s", thread_id, exc_info=True
            )
            return []
        return _find_pending_message_tool_calls(thread_state)

    def _build_inline_callback_data(self, button_index: int) -> str:
        return f"{_MESSAGE_TOOL_CALLBACK_PREFIX}{button_index}"

    def _parse_inline_callback_data(self, data: str | None) -> int | None:
        if not isinstance(data, str) or not data.startswith(
            _MESSAGE_TOOL_CALLBACK_PREFIX
        ):
            return None
        raw_index = data[len(_MESSAGE_TOOL_CALLBACK_PREFIX) :]
        if not raw_index.isdigit():
            return None
        return int(raw_index)

    def _build_prompt_reply_markup(
        self,
        prompt: TelegramMessageToolPayload,
    ) -> tg_types.InlineKeyboardMarkup | None:
        keyboard: list[list[tg_types.InlineKeyboardButton]] = []
        current_row: list[tg_types.InlineKeyboardButton] = []
        current_row_text_len = 0
        for index, button in enumerate(prompt.buttons):
            if not button.text:
                continue
            if button.kind == "url" and button.url:
                inline_button = tg_types.InlineKeyboardButton(
                    text=button.text,
                    url=button.url,
                )
            else:
                inline_button = tg_types.InlineKeyboardButton(
                    text=button.text,
                    callback_data=self._build_inline_callback_data(index),
                )
            button_text_len = len(button.text)
            should_wrap = bool(
                current_row
                and (
                    len(current_row) >= 4 or current_row_text_len + button_text_len > 20
                )
            )
            if should_wrap:
                keyboard.append(current_row)
                current_row = []
                current_row_text_len = 0

            current_row.append(inline_button)
            current_row_text_len += button_text_len

        if current_row:
            keyboard.append(current_row)

        if not keyboard:
            return None
        return tg_types.InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _resolve_callback_button(
        self,
        prompt: TelegramMessageToolPayload,
        callback_data: str | None,
    ) -> tuple[str, str] | None:
        button_index = self._parse_inline_callback_data(callback_data)
        if button_index is None:
            return None
        buttons = [button for button in prompt.buttons if button.text]
        if button_index < 0 or button_index >= len(buttons):
            return None
        button = buttons[button_index]
        if button.kind == "url":
            return None
        response_text = button.value or button.text
        return button.text, response_text

    def _convert_plotly_attachment(
        self,
        *,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[bytes, str, bool]:
        lower = filename.lower()
        if not (lower.endswith(".plotly.json") or lower.endswith("plotly.json")):
            return file_bytes, filename, False

        png_bytes = _plotly_json_to_png_bytes(payload_bytes=file_bytes)
        if not png_bytes:
            return file_bytes, filename, False

        png_name = re.sub(r"(?i)\.plotly\.json$", ".png", filename)
        if png_name == filename:
            png_name = re.sub(r"(?i)\.json$", ".png", filename)
        if png_name == filename:
            png_name = f"{filename}.png"
        return png_bytes, png_name, True

    async def _send_message_tool_prompt(
        self,
        message: tg_types.Message,
        token: str,
        tool_call: dict[str, Any],
        reply_to_message_id: int | None = None,
        include_reply_markup: bool = True,
    ) -> None:
        prompt = parse_telegram_message_tool_payload(tool_call.get("args"))
        reply_kwargs = self._build_reply_kwargs(reply_to_message_id)
        for attachment in prompt.attachments:
            file_bytes = await self._download_attachment(token, attachment.path)
            if not file_bytes:
                continue
            filename = attachment.filename or attachment.path.rsplit("/", 1)[-1]
            file_bytes, filename, rendered_from_plotly = (
                self._convert_plotly_attachment(
                    file_bytes=file_bytes,
                    filename=filename,
                )
            )
            input_file = BufferedInputFile(file_bytes, filename=filename)
            caption = attachment.caption or None
            kind = attachment.kind
            if rendered_from_plotly or kind == "image":
                await message.answer_photo(input_file, caption=caption, **reply_kwargs)
            elif kind == "audio":
                await message.answer_audio(input_file, caption=caption, **reply_kwargs)
            elif kind == "video":
                await message.answer_video(input_file, caption=caption, **reply_kwargs)
            else:
                await message.answer_document(
                    input_file, caption=caption, **reply_kwargs
                )

        reply_markup = (
            self._build_prompt_reply_markup(prompt) if include_reply_markup else None
        )
        chunks = _split_message(prompt.content)
        for idx, chunk in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            markup = reply_markup if is_last else None
            tg_text = _md_to_tg_markdown_v2(chunk)
            try:
                await message.answer(
                    tg_text,
                    parse_mode="MarkdownV2",
                    reply_markup=markup,
                    disable_web_page_preview=prompt.disable_web_page_preview,
                    **reply_kwargs,
                )
            except Exception:
                await message.answer(
                    chunk,
                    reply_markup=markup,
                    disable_web_page_preview=prompt.disable_web_page_preview,
                    **reply_kwargs,
                )

    async def _continue_run_until_ready(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        token: str,
        result: Any,
        run_timeout: int,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        for _ in range(10):
            if not isinstance(result, dict):
                return None

            pending_message_tools = await self._get_pending_message_tool_calls(
                client,
                thread_id,
            )
            if pending_message_tools:
                last_pending_message_tool = pending_message_tools[-1]
                prompt = parse_telegram_message_tool_payload(
                    last_pending_message_tool.get("args"),
                )
                for index, pending_message_tool in enumerate(pending_message_tools):
                    await self._send_message_tool_prompt(
                        message,
                        token,
                        pending_message_tool,
                        reply_to_message_id,
                        include_reply_markup=index == len(pending_message_tools) - 1,
                    )
                if not prompt.expect_response:
                    result = await self._resume_message_tool_calls(
                        message=message,
                        client=client,
                        thread_id=thread_id,
                        pending_tool_calls=pending_message_tools,
                        response_tool_call=last_pending_message_tool,
                        response_prompt=prompt,
                        response_text="",
                        file_data=[],
                        run_timeout=run_timeout,
                        auto_response=True,
                    )
                    continue
                return None

            msgs = result.get("messages", [])
            last_ai = None
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("type") == "ai":
                    last_ai = m
                    break
            if last_ai and last_ai.get("tool_calls"):
                logger.info("Auto-approving tool calls for chat %s", message.chat.id)
                await message.chat.do("typing")
                result = await asyncio.wait_for(
                    client.runs.wait(
                        thread_id=thread_id,
                        assistant_id=ASSISTANT_ID,
                        input=None,
                        command={"resume": {"type": "approve"}},
                    ),
                    timeout=run_timeout,
                )
                continue
            return result
        return result if isinstance(result, dict) else None

    async def _resume_message_tool_call(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        pending_tool_call: dict[str, Any],
        prompt: TelegramMessageToolPayload,
        response_text: str,
        file_data: list[dict[str, Any]],
        run_timeout: int,
        auto_response: bool = False,
        selected_button: str = "",
    ) -> dict[str, Any]:
        return await self._resume_message_tool_calls(
            message=message,
            client=client,
            thread_id=thread_id,
            pending_tool_calls=[pending_tool_call],
            response_tool_call=pending_tool_call,
            response_prompt=prompt,
            response_text=response_text,
            file_data=file_data,
            run_timeout=run_timeout,
            auto_response=auto_response,
            selected_button=selected_button,
        )

    async def _resume_message_tool_calls(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        pending_tool_calls: list[dict[str, Any]],
        response_tool_call: dict[str, Any],
        response_prompt: TelegramMessageToolPayload,
        response_text: str,
        file_data: list[dict[str, Any]],
        run_timeout: int,
        auto_response: bool = False,
        selected_button: str = "",
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        response_tool_id = response_tool_call.get("id")
        for pending_tool_call in pending_tool_calls:
            is_response_tool = pending_tool_call.get("id") == response_tool_id
            if not is_response_tool:
                results.append(
                    {
                        "id": pending_tool_call.get("id"),
                        "result": {},
                    }
                )
                continue

            results.append(
                {
                    "id": pending_tool_call.get("id"),
                    "result": {
                        "content": _build_message_tool_result_parts(
                            prompt=response_prompt,
                            response_text=response_text,
                            file_data=file_data,
                            message=message,
                            auto_response=auto_response,
                            selected_button=selected_button,
                        ),
                    },
                }
            )

        await message.chat.do("typing")
        return await asyncio.wait_for(
            client.runs.wait(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                input=None,
                command={
                    "resume": {
                        "type": "tool_call",
                        "results": results,
                    },
                },
            ),
            timeout=run_timeout,
        )

    async def _resume_pending_message_tool(
        self,
        *,
        message: tg_types.Message,
        client: Any,
        thread_id: str,
        token: str,
        pending_tool_calls: list[dict[str, Any]],
        run_timeout: int,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        pending_tool_call = pending_tool_calls[-1]
        file_data = await self._collect_incoming_files(message, token, thread_id)
        text = message.text or message.caption or ""
        response_text = text or _describe_uploaded_files(file_data)
        prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
        result = await self._resume_message_tool_calls(
            message=message,
            client=client,
            thread_id=thread_id,
            pending_tool_calls=pending_tool_calls,
            response_tool_call=pending_tool_call,
            response_prompt=prompt,
            response_text=response_text,
            file_data=file_data,
            run_timeout=run_timeout,
        )
        return await self._continue_run_until_ready(
            message=message,
            client=client,
            thread_id=thread_id,
            token=token,
            result=result,
            run_timeout=run_timeout,
            reply_to_message_id=reply_to_message_id,
        )

    async def _send_run_result(
        self,
        *,
        message: tg_types.Message,
        token: str,
        result: dict[str, Any],
        request_start: Any,
        reply_to_message_id: int | None = None,
    ) -> None:
        response_text, image_urls = _extract_ai_response(result)
        response_text, attachment_paths = _extract_attachments(response_text)
        reply_kwargs = self._build_reply_kwargs(reply_to_message_id)

        if not attachment_paths:
            attachment_paths = _scan_current_turn_attachments(result)

        # Robust fallback: if tool calls happened but no attachments found,
        # check files API for recently created image files
        if not attachment_paths and not image_urls:
            has_tool_calls = any(
                isinstance(m, dict) and m.get("type") == "ai" and m.get("tool_calls")
                for m in (result.get("messages") or [])[
                    _find_last_human_index(result.get("messages") or []) :
                ]
            )
            if has_tool_calls:
                attachment_paths = await self._find_recent_image_files(
                    token,
                    request_start,
                )

        logger.info(
            "Response for chat %s: text=%d chars, images=%d, attachments=%d",
            message.chat.id,
            len(response_text),
            len(image_urls),
            len(attachment_paths),
        )

        sent_any = False

        for path in attachment_paths[:10]:
            try:
                file_bytes = await self._download_attachment(token, path)
                if file_bytes:
                    fname = path.rsplit("/", 1)[-1] if "/" in path else path
                    file_bytes, fname, rendered_from_plotly = (
                        self._convert_plotly_attachment(
                            file_bytes=file_bytes,
                            filename=fname,
                        )
                    )
                    inp = BufferedInputFile(file_bytes, filename=fname)
                    lower = fname.lower()
                    if rendered_from_plotly or lower.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ):
                        await message.answer_photo(inp, **reply_kwargs)
                    else:
                        await message.answer_document(inp, **reply_kwargs)
                    sent_any = True
            except Exception:
                logger.warning("Failed to send attachment %s", path[:80])

        for url in image_urls[:5]:
            try:
                await self._send_image(
                    message,
                    url,
                    reply_to_message_id=reply_to_message_id,
                )
                sent_any = True
            except Exception:
                logger.warning("Failed to send image to Telegram")

        if response_text:
            for chunk in _split_message(response_text):
                tg_text = _md_to_tg_markdown_v2(chunk)
                try:
                    await message.answer(
                        tg_text,
                        parse_mode="MarkdownV2",
                        **reply_kwargs,
                    )
                except Exception:
                    # Fallback to plain text if formatting fails
                    await message.answer(chunk, **reply_kwargs)
            sent_any = True

        if not sent_any:
            await message.answer("✅ Задача выполнена.", **reply_kwargs)

    async def _handle_callback_query(self, callback: tg_types.CallbackQuery) -> None:
        message = callback.message
        if message is None:
            await callback.answer()
            return
        if not await self._ensure_supported_chat(message, callback=callback):
            return

        chat_id = message.chat.id
        user_id = self.bot_row.user_id
        from datetime import datetime, timezone

        request_start = datetime.now(timezone.utc)

        try:
            session_factory = await get_session_factory()
            await self._register_contact(message)
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                contact = await repo.get_contact(self.bot_row.id, chat_id)
                if contact is None or not contact.is_approved:
                    await callback.answer("Контакт не подтверждён", show_alert=True)
                    return

            token = _make_token(user_id, self.user_email)
            client = get_client(
                url=_langgraph_url(),
                headers={"Authorization": f"Bearer {token}"},
            )

            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                thread_id = await self._get_or_create_thread(client, repo, callback.from_user.id)

            pending_tool_calls = await self._get_pending_message_tool_calls(
                client, thread_id
            )
            if not pending_tool_calls:
                await callback.answer("Ожидание ответа уже завершено")
                return

            pending_tool_call = pending_tool_calls[-1]
            prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
            resolved = self._resolve_callback_button(prompt, callback.data)
            if resolved is None:
                await callback.answer("Кнопка больше неактуальна", show_alert=True)
                return

            selected_button, response_text = resolved
            await callback.answer()
            result = await self._resume_message_tool_calls(
                message=message,
                client=client,
                thread_id=thread_id,
                pending_tool_calls=pending_tool_calls,
                response_tool_call=pending_tool_call,
                response_prompt=prompt,
                response_text=response_text,
                file_data=[],
                run_timeout=90,
                selected_button=selected_button,
            )
            result = await self._continue_run_until_ready(
                message=message,
                client=client,
                thread_id=thread_id,
                token=token,
                result=result,
                run_timeout=90,
            )
            if isinstance(result, dict) and result.get("messages"):
                await self._send_run_result(
                    message=message,
                    token=token,
                    result=result,
                    request_start=request_start,
                )
        except asyncio.TimeoutError:
            await callback.answer("Истекло время ожидания", show_alert=True)
        except Exception:
            logger.exception("Error handling Telegram callback for user %s", user_id)
            try:
                await callback.answer("Не удалось обработать нажатие", show_alert=True)
            except Exception:
                pass

    async def _handle_message(
        self,
        message: tg_types.Message,
        *,
        force_process: bool = False,
        reply_to_message_id: int | None = None,
        contact_message: tg_types.Message | None = None,
        text_override: str | None = None,
    ):
        if not await self._ensure_supported_chat(message):
            return
        if not force_process and not self._should_process_message(message):
            return
        if contact_message is None:
            contact_message = message
        chat_id = message.chat.id
        raw_text = message.text or message.caption or ""
        text = (
            text_override
            if text_override is not None
            else self._strip_bot_mentions(raw_text)
        )
        user_id = self.bot_row.user_id
        reply_kwargs = self._build_reply_kwargs(reply_to_message_id)

        logger.info("Telegram message from chat %s: %s", chat_id, text[:100])
        from datetime import datetime, timezone

        request_start = datetime.now(timezone.utc)

        try:
            session_factory = await get_session_factory()

            # --- Contact approval gate ---
            await self._register_contact(contact_message)
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                contact = await repo.get_contact(self.bot_row.id, chat_id)
                if contact is None or not contact.is_approved:
                    await message.answer(
                        "⏳ Ваш контакт ожидает подтверждения. "
                        "Владелец бота должен одобрить вас в настройках."
                        ,
                        **reply_kwargs,
                    )
                    return

            token = _make_token(user_id, self.user_email)
            client = get_client(
                url="http://localhost:9090/api/",
                headers={"Authorization": f"Bearer {token}"},
            )

            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                thread_id = await self._get_or_create_thread(client, repo, message.from_user.id)

            RUN_TIMEOUT = 90  # seconds per run

            pending_message_tools = await self._get_pending_message_tool_calls(
                client,
                thread_id,
            )
            if pending_message_tools:
                result = await self._resume_pending_message_tool(
                    message=message,
                    client=client,
                    thread_id=thread_id,
                    token=token,
                    pending_tool_calls=pending_message_tools,
                    run_timeout=RUN_TIMEOUT,
                    reply_to_message_id=reply_to_message_id,
                )
                if result is None:
                    return
            else:
                await message.chat.do("typing")
                reply_message = getattr(message, "reply_to_message", None)
                reply_text = ""
                reply_file_data: list[dict[str, Any]] = []
                if reply_message is not None:
                    reply_text = reply_message.text or reply_message.caption or ""
                    reply_file_data = await self._collect_incoming_files(
                        reply_message,
                        token,
                        thread_id,
                    )

                file_data = await self._collect_incoming_files(message, token, thread_id)
                all_file_data = [*reply_file_data, *file_data]
                if all_file_data:
                    logger.info(
                        "Files for agent: %s",
                        [fd["path"] for fd in all_file_data],
                    )

                content_parts = []
                content_parts.append(
                    self._build_message_context(
                        label="Входящее сообщение к агенту",
                        message=message,
                        text=text,
                        files=file_data,
                    )
                )
                if reply_message is not None:
                    content_parts.append(
                        self._build_message_context(
                            label="Прикрепено сообщение",
                            message=reply_message,
                            text=reply_text,
                            files=reply_file_data,
                        )
                    )
                content = "\n\n".join(content_parts)
                content += (
                    "\n\n[system: Ответ будет отправлен в Telegram. "
                    "Если ты выполняешь долгую операцию, например вызываешь субагентов, то вызови message тул с уведомлением о том, что будешь делать с except_response=False"
                    "Активно планируй и следуй своему плану! Всегда перед вызовом тулов размышляй над задачей и пиши размышления в тег <thinking>"
                    "Действуй по простым шагам!"
                    "Следующий шаг: "
                )
                human_msg: dict[str, Any] = {"role": "human", "content": content}
                if all_file_data:
                    human_msg["additional_kwargs"] = {
                        "user_input": content,
                        "files": all_file_data,
                    }

                run_input: dict[str, Any] = {
                    "messages": [human_msg],
                    "mcp_tools": [build_telegram_message_tool_schema()],
                }
                collections_payload = await self._load_collections_payload()
                if collections_payload:
                    run_input["collections"] = collections_payload

                result = await asyncio.wait_for(
                    client.runs.wait(
                        thread_id=thread_id,
                        assistant_id=ASSISTANT_ID,
                        input=run_input,
                    ),
                    timeout=RUN_TIMEOUT,
                )
                result = await self._continue_run_until_ready(
                    message=message,
                    client=client,
                    thread_id=thread_id,
                    token=token,
                    result=result,
                    run_timeout=RUN_TIMEOUT,
                    reply_to_message_id=reply_to_message_id,
                )
                if result is None:
                    return

            if not isinstance(result, dict) or not result.get("messages"):
                logger.warning(
                    "Empty result for chat %s: %s", chat_id, str(result)[:500]
                )
                async with session_factory() as session:
                    repo = TelegramBotRepository(session)
                    await self._reset_thread(repo, chat_id)
                await message.answer(
                    "⚠️ Агент не вернул ответ. Попробуйте ещё раз.",
                    **reply_kwargs,
                )
                return
            await self._send_run_result(
                message=message,
                token=token,
                result=result,
                request_start=request_start,
                reply_to_message_id=reply_to_message_id,
            )

        except asyncio.TimeoutError:
            logger.warning(
                "Timeout handling Telegram message for user %s (chat %s)",
                user_id,
                chat_id,
            )
            try:
                async with (await get_session_factory())() as session:
                    repo = TelegramBotRepository(session)
                    await self._reset_thread(repo, chat_id)
            except Exception:
                pass
            try:
                await message.answer(
                    "⏱ Время ожидания ответа истекло. Попробуйте ещё раз.",
                    **reply_kwargs,
                )
            except Exception:
                pass
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
                    await message.answer(
                        "⚠️ Контекст повреждён, сброшен. Повторите сообщение.",
                        **reply_kwargs,
                    )
                except Exception:
                    pass
            else:
                try:
                    await message.answer(
                        "⚠️ Произошла ошибка при обработке сообщения.",
                        **reply_kwargs,
                    )
                except Exception:
                    pass

    async def _download_attachment(self, token: str, path: str) -> bytes | None:
        import httpx

        base = _agent_api_base()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{base}/files/content/by-path",
                params={"path": path},
                headers=headers,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.content

            # Fallback: path suffix may differ after upload; search by UUID prefix
            filename = path.rsplit("/", 1)[-1] if "/" in path else path
            uuid_prefix = (
                filename.split("--")[0]
                if "--" in filename
                else filename.rsplit(".", 1)[0]
            )
            if uuid_prefix:
                try:
                    files_resp = await http.get(f"{base}/files", headers=headers)
                    if files_resp.status_code == 200:
                        for f in files_resp.json():
                            sp = f.get("sandbox_path", "")
                            if uuid_prefix in sp and sp != path:
                                resp2 = await http.get(
                                    f"{base}/files/content/by-path",
                                    params={"path": sp},
                                    headers=headers,
                                    follow_redirects=True,
                                )
                                if resp2.status_code == 200:
                                    return resp2.content
                except Exception:
                    pass

        # Fallback: file may exist in sandbox but not registered in files DB
        # (e.g. created via plt.savefig() without going through upload mechanism)
        if path.startswith("/bucket/"):
            try:
                from giga_agent.sandbox.manager.facade import SandboxManager
                from giga_agent.core.db import get_session_factory

                factory = await get_session_factory()
                async with factory() as session:
                    manager = SandboxManager(session)
                    sandbox = await manager.get_cached_or_db(
                        user_id=self.bot_row.user_id,
                    )
                    result = await sandbox.read_file(path)
                    if hasattr(result, "data") and result.data:
                        return result.data
                    if hasattr(result, "stream"):
                        chunks = []
                        async for chunk in result.stream:
                            chunks.append(chunk)
                        return b"".join(chunks)
            except Exception:
                logger.warning("Sandbox fallback also failed for %s", path[:80])

        logger.warning("Failed to download %s: %d", path[:80], resp.status_code)
        return None

    async def _find_recent_image_files(self, token: str, since: Any) -> list[str]:
        """Check files API for image files created after `since`."""
        import httpx

        base = _agent_api_base()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(f"{base}/files", headers=headers)
                if resp.status_code != 200:
                    return []
                paths = []
                for f in resp.json():
                    ft = f.get("file_type", "")
                    if ft not in ("image", "plotly_graph"):
                        continue
                    created = f.get("created_at", "")
                    if not created:
                        continue
                    from datetime import datetime, timezone

                    try:
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= since:
                            paths.append(f["sandbox_path"])
                    except Exception:
                        continue
                if paths:
                    logger.info(
                        "Found %d recent image files via files API fallback", len(paths)
                    )
                return paths
        except Exception:
            return []

    async def _send_image(
        self,
        message: tg_types.Message,
        url: str,
        *,
        reply_to_message_id: int | None = None,
    ):
        reply_kwargs = self._build_reply_kwargs(reply_to_message_id)
        if url.startswith("http"):
            await message.answer_photo(url, **reply_kwargs)
        elif url.startswith("data:image"):
            import base64

            _, b64data = url.split(",", 1)
            photo_bytes = base64.b64decode(b64data)
            await message.answer_photo(
                BufferedInputFile(photo_bytes, filename="image.png"),
                **reply_kwargs,
            )

    async def _set_commands(self) -> None:
        private_commands = [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="new", description="Сбросить контекст диалога"),
            BotCommand(command="message", description="Отправить сообщение агенту"),
        ]
        group_commands = [
            BotCommand(command="new", description="Сбросить контекст диалога"),
            BotCommand(command="message", description="Отправить сообщение агенту"),
        ]

        await self.bot.set_my_commands(
            private_commands,
            scope=BotCommandScopeAllPrivateChats(),
        )
        await self.bot.set_my_commands(
            group_commands,
            scope=BotCommandScopeAllGroupChats(),
        )

    async def start(self):
        logger.info(
            "Starting Telegram bot %s for user %s",
            self.bot_row.bot_username or self.bot_row.id,
            self.bot_row.user_id,
        )
        await self.bot.delete_webhook(drop_pending_updates=True)
        await self._set_commands()
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
