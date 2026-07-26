"""Media transport helpers for Telegram runtime."""

from __future__ import annotations

import base64
import re
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from aiogram import Bot, types as tg_types
from aiogram.types import BufferedInputFile

from giga_agent.channels.telegram.message_context import build_reply_kwargs
from giga_agent.channels.telegram.utils import (
    TelegramTextMediaPart,
    _agent_api_base,
    _extract_ai_response,
    _extract_text_media,
    _md_to_tg_markdown_v2,
    _plotly_json_to_png_bytes,
    _split_message,
)
from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot
from giga_agent.models.sandbox import SandboxRepository
from giga_agent.sandbox.access import (
    append_sandbox_access_token_to_url,
    mint_sandbox_access_token,
    sandbox_redirect_url_pattern,
    sandbox_url_pattern,
)
from giga_agent.sandbox.materialize import materialize_bounded

logger = get_logger(__name__)

# Потолок на медиа, которое телеграм-бот держит в RAM целиком перед отправкой.
MAX_TELEGRAM_MEDIA_BYTES = 50 * 1024 * 1024


def _convert_plotly_attachment(
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


class TelegramMediaService:
    def __init__(self, *, bot: Bot, bot_row: ChannelBot):
        self.bot = bot
        self.bot_row = bot_row

    async def inject_sandbox_access_tokens(self, text: str) -> str:
        """Splice a fresh ``__sbx`` capability token into sandbox URLs in ``text``.

        ``open_port`` hands the model a clean, token-less URL (the owner opens it
        via their session cookie). Telegram recipients have no such cookie, so a
        per-``(sandbox, port)`` token is appended here — by code, not by the
        model, which composes the query unreliably. Only sandboxes owned by this
        bot's user get a token; foreign or unknown URLs are left untouched.

        Two URL shapes are handled:

        * Direct nginx URLs ``https://{port}-sandbox-{hex}.{public_base_domain}/``
          — the token is appended in place.
        * Cross-domain redirect links ``…/sandbox-redirect/{hex}/{port}`` (mode
          ``GIGA_AGENT_SANDBOX_PORT_REDIRECT_BASE``) — these are owner-only
          (session-cookie gated), so they are rewritten into the direct sandbox
          URL on ``{redirect_base}`` with a token, i.e. the exact target the
          redirect endpoint would 302 to, but usable without a cookie.
        """
        if not text:
            return text
        settings = get_settings()
        base_domain = settings.giga_agent_public_base_domain
        redirect_base = settings.giga_agent_sandbox_port_redirect_base

        direct_pattern = (
            sandbox_url_pattern(base_domain)
            if base_domain and "-sandbox-" in text
            else None
        )
        redirect_pattern = (
            sandbox_redirect_url_pattern()
            if redirect_base and "/sandbox-redirect/" in text
            else None
        )
        if direct_pattern is None and redirect_pattern is None:
            return text

        pairs: set[tuple[str, int]] = set()
        for pattern in (direct_pattern, redirect_pattern):
            if pattern is None:
                continue
            pairs.update(
                (match.group("hex"), int(match.group("port")))
                for match in pattern.finditer(text)
            )
        if not pairs:
            return text

        owner_id = str(self.bot_row.user_id)
        tokens: dict[tuple[str, int], str] = {}
        factory = await get_session_factory()
        async with factory() as session:
            repo = SandboxRepository(session)
            for sandbox_hex, port in pairs:
                try:
                    sandbox_id = uuid.UUID(hex=sandbox_hex)
                except ValueError:
                    continue
                resolved_owner = await repo.get_owner_id_by_sandbox_cached(sandbox_id)
                if resolved_owner is None or str(resolved_owner) != owner_id:
                    continue
                tokens[(sandbox_hex, port)] = await mint_sandbox_access_token(
                    sandbox_hex, port
                )
        if not tokens:
            return text

        if direct_pattern is not None:

            def _replace_direct(match: "re.Match[str]") -> str:
                token = tokens.get((match.group("hex"), int(match.group("port"))))
                if not token:
                    return match.group(0)
                return append_sandbox_access_token_to_url(match.group(0), token)

            text = direct_pattern.sub(_replace_direct, text)

        if redirect_pattern is not None:

            def _replace_redirect(match: "re.Match[str]") -> str:
                sandbox_hex = match.group("hex")
                port = int(match.group("port"))
                token = tokens.get((sandbox_hex, port))
                if not token:
                    return match.group(0)
                url = f"https://{port}-sandbox-{sandbox_hex}.{redirect_base}/"
                return append_sandbox_access_token_to_url(url, token)

            text = redirect_pattern.sub(_replace_redirect, text)

        return text

    async def upload_tg_file(
        self,
        token: str,
        file_id: str,
        file_name: str,
        thread_id: str,
    ) -> dict[str, Any] | None:
        """Download file from Telegram and upload to agent file API."""
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
                        "Uploaded file %s -> %s",
                        file_name,
                        result.get("sandbox_path"),
                    )
                    return result
                logger.warning(
                    "File upload failed: %d %s",
                    resp.status_code,
                    resp.text[:300],
                )
        except Exception:
            logger.exception("Failed to upload Telegram file %s", file_name)
        return None

    async def collect_incoming_files(
        self,
        message: tg_types.Message,
        token: str,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        uploaded_files: list[dict[str, Any]] = []
        if message.photo:
            photo = message.photo[-1]
            uploaded = await self.upload_tg_file(
                token,
                photo.file_id,
                "photo.jpg",
                thread_id,
            )
            if uploaded:
                uploaded_files.append(uploaded)
        if message.sticker:
            sticker = message.sticker
            if not sticker.is_animated and not sticker.is_video:
                uploaded = await self.upload_tg_file(
                    token,
                    sticker.file_id,
                    "sticker.jpg",
                    thread_id,
                )
                if uploaded:
                    uploaded_files.append(uploaded)
        if message.document:
            fname = message.document.file_name or "document"
            uploaded = await self.upload_tg_file(
                token,
                message.document.file_id,
                fname,
                thread_id,
            )
            if uploaded:
                uploaded_files.append(uploaded)
        if message.voice:
            uploaded = await self.upload_tg_file(
                token,
                message.voice.file_id,
                "voice.ogg",
                thread_id,
            )
            if uploaded:
                uploaded_files.append(uploaded)
        if message.audio:
            fname = message.audio.file_name or "audio.mp3"
            uploaded = await self.upload_tg_file(
                token,
                message.audio.file_id,
                fname,
                thread_id,
            )
            if uploaded:
                uploaded_files.append(uploaded)
        if message.video:
            fname = message.video.file_name or "video.mp4"
            uploaded = await self.upload_tg_file(
                token,
                message.video.file_id,
                fname,
                thread_id,
            )
            if uploaded:
                uploaded_files.append(uploaded)
        return [
            {
                "path": uploaded["sandbox_path"],
                "original_name": uploaded.get("original_name", ""),
                "file_type": uploaded.get("file_type", "other"),
                "size": uploaded.get("size", 0),
            }
            for uploaded in uploaded_files
        ]

    async def download_attachment(self, token: str, path: str) -> bytes | None:
        base = _agent_api_base()
        headers = {"Authorization": f"Bearer {token}"}
        resp = None
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{base}/files/content/by-path",
                params={"path": path},
                headers=headers,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.content

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
                        for file_info in files_resp.json():
                            sandbox_path = file_info.get("sandbox_path", "")
                            if uuid_prefix in sandbox_path and sandbox_path != path:
                                resp2 = await http.get(
                                    f"{base}/files/content/by-path",
                                    params={"path": sandbox_path},
                                    headers=headers,
                                    follow_redirects=True,
                                )
                                if resp2.status_code == 200:
                                    return resp2.content
                except Exception:
                    pass

        if path.startswith("/bucket/"):
            try:
                from giga_agent.sandbox.manager.facade import SandboxManager

                factory = await get_session_factory()
                async with factory() as session:
                    manager = SandboxManager(session)
                    sandbox = await manager.get_cached_or_db(
                        user_id=self.bot_row.user_id,
                    )
                    result = await sandbox.read_file(path)
                    data, too_large = await materialize_bounded(
                        result, MAX_TELEGRAM_MEDIA_BYTES
                    )
                    if too_large:
                        logger.warning(
                            "Sandbox media %s exceeds telegram limit, skipping",
                            path[:80],
                        )
                        return None
                    if data is not None:
                        return data
            except Exception:
                logger.warning("Sandbox fallback also failed for %s", path[:80])

        status_code = getattr(resp, "status_code", 0)
        logger.warning("Failed to download %s: %d", path[:80], status_code)
        return None

    async def find_recent_image_files(self, token: str, since: Any) -> list[str]:
        """Check files API for image files created after `since`."""
        base = _agent_api_base()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(f"{base}/files", headers=headers)
                if resp.status_code != 200:
                    return []
                paths = []
                for file_info in resp.json():
                    file_type = file_info.get("file_type", "")
                    if file_type not in ("image", "plotly_graph"):
                        continue
                    created = file_info.get("created_at", "")
                    if not created:
                        continue
                    try:
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= since:
                            paths.append(file_info["sandbox_path"])
                    except Exception:
                        continue
                if paths:
                    logger.info(
                        "Found %d recent image files via files API fallback",
                        len(paths),
                    )
                return paths
        except Exception:
            return []

    async def send_image(
        self,
        message: tg_types.Message,
        url: str,
        *,
        reply_to_message_id: int | None = None,
        reply_markup: Any = None,
    ) -> None:
        reply_kwargs = build_reply_kwargs(reply_to_message_id)
        if url.startswith("http"):
            await message.answer_photo(url, reply_markup=reply_markup, **reply_kwargs)
        elif url.startswith("data:image"):
            _, b64data = url.split(",", 1)
            photo_bytes = base64.b64decode(b64data)
            await message.answer_photo(
                BufferedInputFile(photo_bytes, filename="image.png"),
                reply_markup=reply_markup,
                **reply_kwargs,
            )

    async def send_embedded_media(
        self,
        *,
        message: tg_types.Message,
        token: str,
        parts: list[TelegramTextMediaPart],
        reply_to_message_id: int | None = None,
        reply_markup: Any = None,
        disable_web_page_preview: bool = False,
    ) -> bool:
        reply_kwargs = build_reply_kwargs(reply_to_message_id)
        send_ops: list[TelegramTextMediaPart] = []
        attachment_count = 0
        image_count = 0

        for part in parts:
            kind = part["kind"]
            value = part["value"]
            if kind == "text":
                for chunk in _split_message(value):
                    if chunk:
                        send_ops.append({"kind": "text", "value": chunk})
                continue
            if kind == "attachment_path":
                if attachment_count >= 10:
                    continue
                attachment_count += 1
            elif kind == "image_url":
                if image_count >= 5:
                    continue
                image_count += 1
            send_ops.append(part)

        sent_any = False

        total_items = len(send_ops)
        for index, part in enumerate(send_ops):
            markup = reply_markup if index == total_items - 1 else None
            kind = part["kind"]
            value = part["value"]
            try:
                if kind == "text":
                    value = await self.inject_sandbox_access_tokens(value)
                    tg_text = _md_to_tg_markdown_v2(value)
                    try:
                        await message.answer(
                            tg_text,
                            parse_mode="MarkdownV2",
                            reply_markup=markup,
                            disable_web_page_preview=disable_web_page_preview,
                            **reply_kwargs,
                        )
                    except Exception as exc:
                        logger.exception("Error sending message to Telegram: %s", exc)
                        await message.answer(
                            value,
                            reply_markup=markup,
                            disable_web_page_preview=disable_web_page_preview,
                            **reply_kwargs,
                        )
                    sent_any = True
                    continue

                if kind == "attachment_path":
                    file_bytes = await self.download_attachment(token, value)
                    if not file_bytes:
                        continue
                    filename = value.rsplit("/", 1)[-1] if "/" in value else value
                    file_bytes, filename, rendered_from_plotly = (
                        _convert_plotly_attachment(
                            file_bytes=file_bytes,
                            filename=filename,
                        )
                    )
                    input_file = BufferedInputFile(file_bytes, filename=filename)
                    lower = filename.lower()
                    if rendered_from_plotly or lower.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ):
                        await message.answer_photo(
                            input_file,
                            reply_markup=markup,
                            **reply_kwargs,
                        )
                    else:
                        await message.answer_document(
                            input_file,
                            reply_markup=markup,
                            **reply_kwargs,
                        )
                    sent_any = True
                    continue

                if kind == "image_url":
                    await self.send_image(
                        message,
                        value,
                        reply_to_message_id=reply_to_message_id,
                        reply_markup=markup,
                    )
                    sent_any = True
            except Exception:
                traceback.print_exc()
                if kind == "attachment_path":
                    logger.warning("Failed to send attachment %s", value[:80])
                elif kind == "image_url":
                    logger.warning("Failed to send image to Telegram")

        return sent_any

    async def send_parts_to_chat(
        self,
        *,
        chat_id: int | str,
        token: str,
        parts: list[TelegramTextMediaPart],
        disable_web_page_preview: bool = False,
    ) -> bool:
        """Send rendered parts directly to a chat_id (proactive delivery).

        Mirrors :meth:`send_embedded_media` but targets ``chat_id`` via
        ``bot.send_*`` instead of replying to an incoming ``message``.
        """
        target: int | str = chat_id
        if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
            target = int(chat_id)

        send_ops: list[TelegramTextMediaPart] = []
        attachment_count = 0
        image_count = 0
        for part in parts:
            kind = part["kind"]
            value = part["value"]
            if kind == "text":
                for chunk in _split_message(value):
                    if chunk:
                        send_ops.append({"kind": "text", "value": chunk})
                continue
            if kind == "attachment_path":
                if attachment_count >= 10:
                    continue
                attachment_count += 1
            elif kind == "image_url":
                if image_count >= 5:
                    continue
                image_count += 1
            send_ops.append(part)

        sent_any = False
        for part in send_ops:
            kind = part["kind"]
            value = part["value"]
            try:
                if kind == "text":
                    value = await self.inject_sandbox_access_tokens(value)
                    tg_text = _md_to_tg_markdown_v2(value)
                    try:
                        await self.bot.send_message(
                            target,
                            tg_text,
                            parse_mode="MarkdownV2",
                            disable_web_page_preview=disable_web_page_preview,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Error delivering message to Telegram: %s", exc
                        )
                        await self.bot.send_message(
                            target,
                            value,
                            disable_web_page_preview=disable_web_page_preview,
                        )
                    sent_any = True
                    continue

                if kind == "attachment_path":
                    file_bytes = await self.download_attachment(token, value)
                    if not file_bytes:
                        continue
                    filename = value.rsplit("/", 1)[-1] if "/" in value else value
                    file_bytes, filename, rendered_from_plotly = (
                        _convert_plotly_attachment(
                            file_bytes=file_bytes,
                            filename=filename,
                        )
                    )
                    input_file = BufferedInputFile(file_bytes, filename=filename)
                    lower = filename.lower()
                    if rendered_from_plotly or lower.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ):
                        await self.bot.send_photo(target, input_file)
                    else:
                        await self.bot.send_document(target, input_file)
                    sent_any = True
                    continue

                if kind == "image_url":
                    if value.startswith("http"):
                        await self.bot.send_photo(target, value)
                    elif value.startswith("data:image"):
                        _, b64data = value.split(",", 1)
                        await self.bot.send_photo(
                            target,
                            BufferedInputFile(
                                base64.b64decode(b64data), filename="image.png"
                            ),
                        )
                    sent_any = True
            except Exception:
                traceback.print_exc()
                logger.warning(
                    "Failed to deliver %s part to chat %s", kind, str(target)[:40]
                )

        return sent_any

    async def send_run_result(
        self,
        *,
        message: tg_types.Message,
        token: str,
        result: dict[str, Any],
        request_start: Any,
        reply_to_message_id: int | None = None,
    ) -> None:
        response_text, image_urls = _extract_ai_response(result)
        parts = _extract_text_media(response_text)
        parts.extend({"kind": "image_url", "value": url} for url in image_urls if url)
        reply_kwargs = build_reply_kwargs(reply_to_message_id)
        text_length = sum(
            len(part["value"]) for part in parts if part["kind"] == "text"
        )
        image_count = sum(1 for part in parts if part["kind"] == "image_url")
        attachment_count = sum(1 for part in parts if part["kind"] == "attachment_path")

        logger.info(
            "Response for chat %s: text=%d chars, images=%d, attachments=%d",
            message.chat.id,
            text_length,
            image_count,
            attachment_count,
        )

        sent_any = await self.send_embedded_media(
            message=message,
            token=token,
            parts=parts,
            reply_to_message_id=reply_to_message_id,
        )

        if not sent_any:
            await message.answer("✅ Задача выполнена.", **reply_kwargs)
