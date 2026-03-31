"""Telegram bot runner – starts/stops aiogram bots per user."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

from aiogram import Bot, Dispatcher, types as tg_types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from langgraph_sdk import get_client
from plotly import io as plotly_io

from giga_agent.conf import get_settings, GIGA_AGENT_PREFIX_API
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.modules.auth.security import create_access_token
from giga_agent.modules.telegram.message_tool import (
    TELEGRAM_MESSAGE_TOOL_CHANNEL,
    TELEGRAM_MESSAGE_TOOL_NAME,
    TelegramMessageToolPayload,
    build_telegram_message_tool_schema,
    parse_telegram_message_tool_payload,
)
from giga_agent.modules.telegram.models import (
    TelegramBot as TelegramBotModel,
    TelegramBotRepository,
)

logger = get_logger(__name__)

ASSISTANT_ID = "giga_agent"
THREAD_TTL_SECONDS = 24 * 60 * 60
_MESSAGE_TOOL_CALLBACK_PREFIX = "ga_msg:"


def _langgraph_url() -> str:
    settings = get_settings()
    return settings.giga_agent_langgraph_api_url or "http://localhost:9090/api/"


def _agent_api_base() -> str:
    """Base URL for the agent's own FastAPI routes (mounted at /api)."""
    base = _langgraph_url().rstrip("/")
    return f"{base}{GIGA_AGENT_PREFIX_API}"


def _make_token(user_id: uuid.UUID, email: str) -> str:
    return create_access_token(
        data={"sub": email, "user_id": str(user_id)},
    )


_ATTACHMENT_RE = re.compile(
    r"!\[([^\]]*)\]\(attachment:(/?[^)]+)\)"
)

_BUCKET_PATH_RE = re.compile(
    r"(?:`?)(/bucket/[a-f0-9\-]+/[^\s`\"',)]+\.(?:png|jpg|jpeg|gif|webp|mp3|mp4|pdf|svg))(?:`?)",
    re.IGNORECASE,
)


def _strip_thinking(text: str) -> str:
    return re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()


def _extract_attachments(text: str) -> tuple[str, list[str]]:
    paths: list[str] = []
    for match in _ATTACHMENT_RE.finditer(text):
        paths.append(match.group(2))
    # Fallback: GigaChat often mentions /bucket/... paths as plain text
    if not paths:
        for match in _BUCKET_PATH_RE.finditer(text):
            p = match.group(1)
            if p not in paths:
                paths.append(p)
    cleaned = _ATTACHMENT_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, paths


def _find_last_human_index(messages: list) -> int:
    """Return the index of the last human message, or 0 if none found."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict):
            msg_type = messages[i].get("type") or messages[i].get("role", "")
            if msg_type == "human":
                return i
    return 0


def _scan_current_turn_attachments(result: dict) -> list[str]:
    """Scan only the current turn's messages for attachment paths.

    Locates the last human message (start of the current turn) and
    scans only messages that follow it.  This prevents resending
    attachments from earlier turns.
    """
    paths: list[str] = []
    seen: set[str] = set()
    messages = result.get("messages") or []
    start = _find_last_human_index(messages)
    for msg in messages[start:]:
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
        for att in ak.get("tool_attachments") or []:
            if isinstance(att, dict) and att.get("sandbox_path"):
                p = att["sandbox_path"]
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
        # Scan content for /bucket/ paths (both raw and inside JSON tool output)
        if isinstance(content, str):
            text_to_scan = content
            if content.startswith("{"):
                try:
                    import json as _json
                    tool_data = _json.loads(content)
                    output = tool_data.get("output", "")
                    if isinstance(output, str):
                        text_to_scan = output
                except Exception:
                    pass
            for match in _ATTACHMENT_RE.finditer(text_to_scan):
                p = match.group(2)
                if p not in seen:
                    paths.append(p)
                    seen.add(p)
            for match in _BUCKET_PATH_RE.finditer(text_to_scan):
                p = match.group(1)
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


def _looks_like_plotly_figure(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    data = payload.get("data")
    if not isinstance(data, list):
        return False

    layout = payload.get("layout")
    if layout is not None and not isinstance(layout, dict):
        return False

    frames = payload.get("frames")
    if frames is not None and not isinstance(frames, list):
        return False

    allowed_keys = {"data", "layout", "frames", "config"}
    return bool(set(payload).intersection({"data", "layout", "frames"})) and set(
        payload
    ).issubset(allowed_keys)


def _plotly_json_to_png_bytes(*, payload_bytes: bytes) -> bytes | None:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not _looks_like_plotly_figure(payload):
        return None

    try:
        figure = plotly_io.from_json(json.dumps(payload, ensure_ascii=False))
        return figure.to_image(format="png")
    except ValueError:
        return None


def _state_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_telegram_message_tool_call(action: Any) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("name") != TELEGRAM_MESSAGE_TOOL_NAME:
        return False
    return isinstance(action.get("args") or {}, dict)


def _find_pending_message_tool_call(thread_state: Any) -> dict[str, Any] | None:
    interrupts = _state_get(thread_state, "interrupts", []) or []
    for interrupt_item in interrupts:
        value = _state_get(interrupt_item, "value", {}) or {}
        if not isinstance(value, dict) or value.get("type") != "tool_call":
            continue
        for tool_call in value.get("tools") or []:
            if _is_telegram_message_tool_call(tool_call):
                return tool_call
    return None


def _describe_uploaded_files(file_data: list[dict[str, Any]]) -> str:
    if not file_data:
        return ""
    names = [fd.get("original_name", "") or fd["path"] for fd in file_data]
    return "Прикреплён файл: " + ", ".join(names)


def _build_message_tool_result_parts(
    *,
    prompt: TelegramMessageToolPayload,
    response_text: str,
    file_data: list[dict[str, Any]],
    message: tg_types.Message | None,
    auto_response: bool = False,
    selected_button: str = "",
) -> list[dict[str, str]]:
    button_texts = {
        button.text
        for button in prompt.buttons
        if button.kind == "callback" and button.text
    }
    if not selected_button and response_text in button_texts:
        selected_button = response_text

    if auto_response:
        payload = {"message": "Ты отправил уведомление пользователю (expect_response: false). Если тебе нужен ответ от пользователя, отправляй с expect_response: true."}
    else:
        payload = {
            "channel": TELEGRAM_MESSAGE_TOOL_CHANNEL,
            "kind": "message_response",
            "content": response_text,
            "selected_button": selected_button,
            "response_format": prompt.response_format,
            "files": file_data,
            "auto_response": auto_response,
            "telegram_chat_id": message.chat.id if message else 0,
            "telegram_message_id": message.message_id if message else 0,
            "telegram_user": {
                "id": message.from_user.id if message and message.from_user else 0,
                "username": (
                    message.from_user.username if message and message.from_user else ""
                ),
                "first_name": (
                    message.from_user.first_name if message and message.from_user else ""
                ),
                "last_name": (
                    message.from_user.last_name if message and message.from_user else ""
                ),
            },
        }
    return [
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False),
        }
    ]


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
                message.photo or message.document
                or message.voice or message.audio
                or message.video or message.video_note
                or message.sticker
            )
            if not text and not has_file:
                return
            await self._handle_message(message)

    async def _register_contact(self, message: tg_types.Message) -> None:
        """Upsert the sender as a contact (idempotent, never raises)."""
        try:
            tg_user = message.from_user
            session_factory = await get_session_factory()
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                await repo.upsert_contact(
                    bot_id=self.bot_row.id,
                    telegram_chat_id=message.chat.id,
                    username=tg_user.username if tg_user else None,
                    first_name=tg_user.first_name if tg_user else None,
                    last_name=tg_user.last_name if tg_user else None,
                )
        except Exception:
            logger.warning("Failed to register contact for chat %s", message.chat.id)

    async def _handle_new(self, message: tg_types.Message):
        chat_id = message.chat.id
        session_factory = await get_session_factory()
        async with session_factory() as session:
            repo = TelegramBotRepository(session)
            await self._reset_thread(repo, chat_id)
        await message.answer(
            "🔄 Контекст сброшен. Начнём новый диалог!",
            reply_markup=tg_types.ReplyKeyboardRemove(),
        )

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
                # Verify thread still exists in LangGraph (in-memory store resets on restart)
                try:
                    await client.threads.get(thread_row.langgraph_thread_id)
                    await repo.touch_thread(thread_row)
                    return thread_row.langgraph_thread_id
                except Exception:
                    logger.info("Thread %s no longer exists in LangGraph, recreating", thread_row.langgraph_thread_id)
                    await repo.delete_thread(thread_row)

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
        return [
            {
                "path": f["sandbox_path"],
                "original_name": f.get("original_name", ""),
                "file_type": f.get("file_type", "other"),
                "size": f.get("size", 0),
            }
            for f in uploaded_files
        ]

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
        try:
            thread_state = await client.threads.get_state(thread_id)
        except Exception:
            logger.debug("Failed to fetch thread state for %s", thread_id, exc_info=True)
            return None
        return _find_pending_message_tool_call(thread_state)

    def _build_inline_callback_data(self, button_index: int) -> str:
        return f"{_MESSAGE_TOOL_CALLBACK_PREFIX}{button_index}"

    def _parse_inline_callback_data(self, data: str | None) -> int | None:
        if not isinstance(data, str) or not data.startswith(_MESSAGE_TOOL_CALLBACK_PREFIX):
            return None
        raw_index = data[len(_MESSAGE_TOOL_CALLBACK_PREFIX):]
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
                    len(current_row) >= 4
                    or current_row_text_len + button_text_len > 20
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
    ) -> None:
        prompt = parse_telegram_message_tool_payload(tool_call.get("args"))
        for attachment in prompt.attachments:
            file_bytes = await self._download_attachment(token, attachment.path)
            if not file_bytes:
                continue
            filename = attachment.filename or attachment.path.rsplit("/", 1)[-1]
            file_bytes, filename, rendered_from_plotly = self._convert_plotly_attachment(
                file_bytes=file_bytes,
                filename=filename,
            )
            input_file = BufferedInputFile(file_bytes, filename=filename)
            caption = attachment.caption or None
            kind = attachment.kind
            if rendered_from_plotly or kind == "image":
                await message.answer_photo(input_file, caption=caption)
            elif kind == "audio":
                await message.answer_audio(input_file, caption=caption)
            elif kind == "video":
                await message.answer_video(input_file, caption=caption)
            else:
                await message.answer_document(input_file, caption=caption)

        reply_markup = self._build_prompt_reply_markup(prompt)
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
                )
            except Exception:
                await message.answer(
                    chunk,
                    reply_markup=markup,
                    disable_web_page_preview=prompt.disable_web_page_preview,
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
    ) -> dict[str, Any] | None:
        for _ in range(10):
            if not isinstance(result, dict):
                return None

            pending_message_tool = await self._get_pending_message_tool_call(
                client,
                thread_id,
            )
            if pending_message_tool is not None:
                prompt = parse_telegram_message_tool_payload(
                    pending_message_tool.get("args"),
                )
                await self._send_message_tool_prompt(message, token, pending_message_tool)
                if not prompt.expect_response:
                    result = await self._resume_message_tool_call(
                        message=message,
                        client=client,
                        thread_id=thread_id,
                        pending_tool_call=pending_message_tool,
                        prompt=prompt,
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
        tool_result = {
            "content": _build_message_tool_result_parts(
                prompt=prompt,
                response_text=response_text,
                file_data=file_data,
                message=message,
                auto_response=auto_response,
                selected_button=selected_button,
            ),
        }
        await message.chat.do("typing")
        return await asyncio.wait_for(
            client.runs.wait(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                input=None,
                command={
                    "resume": {
                        "type": "tool_call",
                        "results": [
                            {
                                "id": pending_tool_call.get("id"),
                                "result": tool_result,
                            },
                        ],
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
        pending_tool_call: dict[str, Any],
        run_timeout: int,
    ) -> dict[str, Any] | None:
        file_data = await self._collect_incoming_files(message, token, thread_id)
        text = message.text or message.caption or ""
        response_text = text or _describe_uploaded_files(file_data)
        prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
        result = await self._resume_message_tool_call(
            message=message,
            client=client,
            thread_id=thread_id,
            pending_tool_call=pending_tool_call,
            prompt=prompt,
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
        )

    async def _send_run_result(
        self,
        *,
        message: tg_types.Message,
        token: str,
        result: dict[str, Any],
        request_start: Any,
    ) -> None:
        response_text, image_urls = _extract_ai_response(result)
        response_text, attachment_paths = _extract_attachments(response_text)

        if not attachment_paths:
            attachment_paths = _scan_current_turn_attachments(result)

        # Robust fallback: if tool calls happened but no attachments found,
        # check files API for recently created image files
        if not attachment_paths and not image_urls:
            has_tool_calls = any(
                isinstance(m, dict) and m.get("type") == "ai" and m.get("tool_calls")
                for m in (result.get("messages") or [])[
                    _find_last_human_index(result.get("messages") or [])
                :]
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
                    file_bytes, fname, rendered_from_plotly = self._convert_plotly_attachment(
                        file_bytes=file_bytes,
                        filename=fname,
                    )
                    inp = BufferedInputFile(file_bytes, filename=fname)
                    lower = fname.lower()
                    if rendered_from_plotly or lower.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ):
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
                tg_text = _md_to_tg_markdown_v2(chunk)
                try:
                    await message.answer(tg_text, parse_mode="MarkdownV2")
                except Exception:
                    # Fallback to plain text if formatting fails
                    await message.answer(chunk)
            sent_any = True

        if not sent_any:
            await message.answer("✅ Задача выполнена.")

    async def _handle_callback_query(self, callback: tg_types.CallbackQuery) -> None:
        message = callback.message
        if message is None:
            await callback.answer()
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
                thread_id = await self._get_or_create_thread(client, repo, chat_id)

            pending_tool_call = await self._get_pending_message_tool_call(client, thread_id)
            if pending_tool_call is None:
                await callback.answer("Ожидание ответа уже завершено")
                return

            prompt = parse_telegram_message_tool_payload(pending_tool_call.get("args"))
            resolved = self._resolve_callback_button(prompt, callback.data)
            if resolved is None:
                await callback.answer("Кнопка больше неактуальна", show_alert=True)
                return

            selected_button, response_text = resolved
            await callback.answer()
            result = await self._resume_message_tool_call(
                message=message,
                client=client,
                thread_id=thread_id,
                pending_tool_call=pending_tool_call,
                prompt=prompt,
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

    async def _handle_message(self, message: tg_types.Message):
        chat_id = message.chat.id
        text = message.text or message.caption or ""
        user_id = self.bot_row.user_id

        logger.info("Telegram message from chat %s: %s", chat_id, text[:100])
        from datetime import datetime, timezone
        request_start = datetime.now(timezone.utc)

        try:
            session_factory = await get_session_factory()

            # --- Contact approval gate ---
            await self._register_contact(message)
            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                contact = await repo.get_contact(self.bot_row.id, chat_id)
                if contact is None or not contact.is_approved:
                    await message.answer(
                        "⏳ Ваш контакт ожидает подтверждения. "
                        "Владелец бота должен одобрить вас в настройках."
                    )
                    return

            token = _make_token(user_id, self.user_email)
            client = get_client(
                url="http://localhost:9090/api/",
                headers={"Authorization": f"Bearer {token}"},
            )

            async with session_factory() as session:
                repo = TelegramBotRepository(session)
                thread_id = await self._get_or_create_thread(client, repo, chat_id)

            RUN_TIMEOUT = 90  # seconds per run

            pending_message_tool = await self._get_pending_message_tool_call(
                client,
                thread_id,
            )
            if pending_message_tool is not None:
                result = await self._resume_pending_message_tool(
                    message=message,
                    client=client,
                    thread_id=thread_id,
                    token=token,
                    pending_tool_call=pending_message_tool,
                    run_timeout=RUN_TIMEOUT,
                )
                if result is None:
                    return
            else:
                await message.chat.do("typing")
                file_data = await self._collect_incoming_files(message, token, thread_id)
                if file_data:
                    logger.info("Files for agent: %s", [fd["path"] for fd in file_data])

                content = text or _describe_uploaded_files(file_data)
                content += (
                    "\n\n[system: Ответ будет отправлен в Telegram. "
                    "Если ты выполняешь долгую операцию, например вызываешь субагентов, то вызови message тул с уведомлением о том, что будешь делать с except_response=False"
                    "Активно планируй и следуй своему плану! Всегда перед вызовом тулов размышляй над задачей и пиши размышления в тег <thinking>"
                    "Действуй по простым шагам!"
                    "Следующий шаг: "
                )
                human_msg: dict[str, Any] = {"role": "human", "content": content}
                if file_data:
                    human_msg["additional_kwargs"] = {
                        "user_input": content,
                        "files": file_data,
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
                )
                if result is None:
                    return

            if not isinstance(result, dict) or not result.get("messages"):
                logger.warning("Empty result for chat %s: %s", chat_id, str(result)[:500])
                async with session_factory() as session:
                    repo = TelegramBotRepository(session)
                    await self._reset_thread(repo, chat_id)
                await message.answer("⚠️ Агент не вернул ответ. Попробуйте ещё раз.")
                return
            await self._send_run_result(
                message=message,
                token=token,
                result=result,
                request_start=request_start,
            )

        except asyncio.TimeoutError:
            logger.warning("Timeout handling Telegram message for user %s (chat %s)", user_id, chat_id)
            try:
                async with (await get_session_factory())() as session:
                    repo = TelegramBotRepository(session)
                    await self._reset_thread(repo, chat_id)
            except Exception:
                pass
            try:
                await message.answer("⏱ Время ожидания ответа истекло. Попробуйте ещё раз.")
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
            uuid_prefix = filename.split("--")[0] if "--" in filename else filename.rsplit(".", 1)[0]
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
                    logger.info("Found %d recent image files via files API fallback", len(paths))
                return paths
        except Exception:
            return []

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


def _md_to_tg_markdown_v2(text: str) -> str:
    """Convert standard Markdown to Telegram MarkdownV2 format."""
    # Extract code blocks first to protect them
    code_blocks: list[str] = []

    def _save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save_code_block, text)

    inline_codes: list[str] = []

    def _save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(0))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", _save_inline_code, text)

    # Escape special MarkdownV2 characters (except those used for formatting)
    def _escape(t: str) -> str:
        return re.sub(r"([_\[\]()~>#+\-=|{}.!\\])", r"\\\1", t)

    # Process bold **text** → *text*
    parts = re.split(r"(\*\*(?:(?!\*\*).)+\*\*)", text)
    result_parts: list[str] = []
    for part in parts:
        m = re.match(r"^\*\*(.+)\*\*$", part, re.DOTALL)
        if m:
            result_parts.append(f"*{_escape(m.group(1))}*")
        else:
            # Process italic *text* → _text_ (single asterisks that aren't bold)
            sub_parts = re.split(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", part)
            for i, sp in enumerate(sub_parts):
                if i % 2 == 1:
                    result_parts.append(f"_{_escape(sp)}_")
                else:
                    result_parts.append(_escape(sp))

    text = "".join(result_parts)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    return text


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
