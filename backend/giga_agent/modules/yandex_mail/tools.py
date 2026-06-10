from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.modules.yandex_mail.auth import (
    IMAP_HOST,
    IMAP_PORT,
    SMTP_HOST,
    SMTP_PORT,
    get_mail_auth,
    xoauth2_bytes,
)

# Тело письма легко переваливает контекст GigaChat — режем жёстко.
MAX_BODY_CHARS = 4000
MAX_LIMIT = 30


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _connect(email_addr: str, token: str) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.authenticate("XOAUTH2", lambda _: xoauth2_bytes(email_addr, token))
    return conn


def _extract_text(msg: Message) -> str:
    """Достаёт читаемый текст из (возможно multipart) письма."""
    if msg.is_multipart():
        # приоритет text/plain, иначе первый text/*
        plain = None
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            if ctype == "text/plain" and plain is None:
                plain = part
        target = plain or next(
            (p for p in msg.walk() if p.get_content_type().startswith("text/")),
            None,
        )
        if target is None:
            return ""
        msg = target
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def _search_sync(
    email_addr: str, token: str, folder: str, limit: int
) -> list[dict[str, Any]]:
    conn = _connect(email_addr, token)
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, data = conn.search(None, "ALL")
        ids = data[0].split()
        ids = ids[-limit:][::-1]  # последние N, новые первыми
        out: list[dict[str, Any]] = []
        for mid in ids:
            typ, msg_data = conn.fetch(
                mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )
            if not msg_data or not msg_data[0]:
                continue
            hdr = email.message_from_bytes(msg_data[0][1])
            out.append(
                {
                    "id": mid.decode(),
                    "from": _decode(hdr.get("From")),
                    "subject": _decode(hdr.get("Subject")),
                    "date": hdr.get("Date"),
                }
            )
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _read_sync(
    email_addr: str, token: str, folder: str, message_id: str
) -> dict[str, Any]:
    conn = _connect(email_addr, token)
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, msg_data = conn.fetch(message_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            return {"error": f"Письмо {message_id} не найдено в папке {folder}."}
        msg = email.message_from_bytes(msg_data[0][1])
        body = _extract_text(msg).strip()
        truncated = len(body) > MAX_BODY_CHARS
        if truncated:
            body = body[:MAX_BODY_CHARS] + "…"
        return {
            "id": message_id,
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "subject": _decode(msg.get("Subject")),
            "date": msg.get("Date"),
            "body": body,
            "truncated": truncated,
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@tool(parse_docstring=True)
async def mail_search(
    runtime: ToolRuntime, folder: str = "INBOX", limit: int = 15
) -> dict[str, Any]:
    """Возвращает список последних писем в папке Яндекс.Почты.

    Отдаёт краткие данные (отправитель/тема/дата) без тел. Чтобы прочитать
    письмо целиком — вызови mail_read с его id.

    Args:
        folder: Папка IMAP, например "INBOX" (входящие) или "Sent".
        limit: Сколько последних писем вернуть (максимум 30).
    """
    email_addr, token = await get_mail_auth(runtime)
    limit = max(1, min(limit, MAX_LIMIT))
    items = await asyncio.to_thread(_search_sync, email_addr, token, folder, limit)
    return {"folder": folder, "messages": items}


@tool(parse_docstring=True)
async def mail_read(
    runtime: ToolRuntime, message_id: str, folder: str = "INBOX"
) -> dict[str, Any]:
    """Читает письмо Яндекс.Почты целиком (текст, обрезается при необходимости).

    Args:
        message_id: Идентификатор письма (поле id из mail_search).
        folder: Папка, в которой лежит письмо (по умолчанию "INBOX").
    """
    email_addr, token = await get_mail_auth(runtime)
    return await asyncio.to_thread(
        _read_sync, email_addr, token, folder, message_id
    )


def _send_sync(
    email_addr: str, token: str, to: str, subject: str, body: str
) -> dict[str, Any]:
    msg = EmailMessage()
    msg["From"] = email_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    conn = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
    try:
        auth = base64.b64encode(xoauth2_bytes(email_addr, token)).decode()
        code, resp = conn.docmd("AUTH", "XOAUTH2 " + auth)
        if code != 235:
            return {
                "error": "Ошибка авторизации SMTP (XOAUTH2).",
                "detail": resp.decode(errors="replace") if resp else str(code),
            }
        conn.send_message(msg)
        return {"status": "sent", "to": to, "subject": subject}
    finally:
        try:
            conn.quit()
        except Exception:
            pass


@tool(parse_docstring=True)
async def mail_send(
    runtime: ToolRuntime, to: str, subject: str, body: str
) -> dict[str, Any]:
    """Отправляет письмо с ящика пользователя через Яндекс.Почту (SMTP).

    Используй только при явной просьбе отправить письмо. Отправка требует
    подтверждения пользователя.

    Args:
        to: Адрес получателя.
        subject: Тема письма.
        body: Текст письма.
    """
    email_addr, token = await get_mail_auth(runtime)
    return await asyncio.to_thread(
        _send_sync, email_addr, token, to, subject, body
    )
