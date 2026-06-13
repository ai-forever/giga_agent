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


# Окно сканирования при фильтре: IMAP SEARCH по кириллице капризен (charset),
# поэтому фильтруем заголовки в Python по последним N письмам.
_FILTER_SCAN = 60


def _search_sync(
    email_addr: str,
    token: str,
    folder: str,
    limit: int,
    sender: str = "",
    subject: str = "",
) -> list[dict[str, Any]]:
    conn = _connect(email_addr, token)
    filtering = bool(sender.strip() or subject.strip())
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, data = conn.search(None, "ALL")
        ids = data[0].split()
        # без фильтра — последние limit; с фильтром — сканируем шире, потом режем.
        scan = ids[-(_FILTER_SCAN if filtering else limit) :][::-1]
        want_from = sender.strip().lower()
        want_subj = subject.strip().lower()
        out: list[dict[str, Any]] = []
        for mid in scan:
            typ, msg_data = conn.fetch(
                mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )
            if not msg_data or not msg_data[0]:
                continue
            hdr = email.message_from_bytes(msg_data[0][1])
            frm = _decode(hdr.get("From"))
            subj = _decode(hdr.get("Subject"))
            if want_from and want_from not in frm.lower():
                continue
            if want_subj and want_subj not in subj.lower():
                continue
            out.append(
                {
                    "id": mid.decode(),
                    "from": frm,
                    "subject": subj,
                    "date": hdr.get("Date"),
                }
            )
            if len(out) >= limit:
                break
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


PROVIDER = "yandex_mail"
MAIL_INBOX_WIDGET = "mail_inbox"


def inbox_payload(folder: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Нормализованный payload входящих — фронт рендерит mail_inbox по маркеру."""
    return {
        "widget": MAIL_INBOX_WIDGET,
        "provider": PROVIDER,
        "folder": folder,
        "messages": messages,
    }


@tool(parse_docstring=True)
async def mail_search(
    runtime: ToolRuntime,
    folder: str = "INBOX",
    limit: int = 15,
    sender: str = "",
    subject: str = "",
) -> dict[str, Any]:
    """Возвращает список писем в папке Яндекс.Почты, по желанию с фильтром.

    Если просят письма от кого-то («от Сбербанка») — передай sender; по теме —
    subject. Фильтр по подстроке без учёта регистра среди последних писем.
    Отдаёт краткие данные (отправитель/тема/дата) без тел; чтобы прочитать
    письмо целиком — вызови mail_read с его id.

    Args:
        folder: Папка IMAP, например "INBOX" (входящие) или "Sent".
        limit: Сколько писем вернуть (максимум 30).
        sender: Фильтр по отправителю (имя или адрес), напр. "сбербанк".
        subject: Фильтр по теме письма.
    """
    email_addr, token = await get_mail_auth(runtime)
    limit = max(1, min(limit, MAX_LIMIT))
    items = await asyncio.to_thread(
        _search_sync, email_addr, token, folder, limit, sender, subject
    )
    return inbox_payload(folder, items)


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
