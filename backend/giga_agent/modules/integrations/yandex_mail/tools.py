from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import re
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from typing import Any

from bs4 import BeautifulSoup
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from markdownify import markdownify as _md

from giga_agent.core.agent.tool_policy import (
    ToolConfirmation,
    ToolEffect,
    tool_extras,
)
from giga_agent.core.agent.tool_results import build_widget_tool_message
from giga_agent.modules.integrations.widget_hint import with_widget_note
from giga_agent.modules.integrations.yandex_mail.auth import (
    IMAP_HOST,
    IMAP_PORT,
    SMTP_HOST,
    SMTP_PORT,
    get_mail_auth,
    xoauth2_bytes,
)

# Тело письма легко переваливает контекст GigaChat — режем жёстко.
MAX_BODY_CHARS = 4000
# HTML-вёрстка (только для виджета, не для модели) — потолок пощедрее; режем
# грубо по символам (браузер в iframe терпим к незакрытым тегам).
MAX_HTML_CHARS = 300_000
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


def _extract_html(msg: Message) -> str:
    """Достаёт text/html-часть письма (для рендера вёрстки в iframe виджета)."""
    target: Message | None = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() != "text/html":
                continue
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            target = part
            break
    elif msg.get_content_type() == "text/html":
        target = msg
    if target is None:
        return ""
    payload = target.get_payload(decode=True)
    if payload is None:
        return ""
    charset = target.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


# Zero-width символы (спейсеры вёрстки писем) — удаляем целиком.
_ZERO_WIDTH_MAP = dict.fromkeys(map(ord, "​‌‍﻿"), None)


def _flatten_html_tables(html: str) -> str:
    """Расплющивает таблицы вёрстки письма ДО конвертации в markdown.

    Письма верстают вложенными layout-таблицами со спейсерами; markdownify
    превращает их в гигантские пустые markdown-таблицы (`| | |` + `| --- |`).
    Разворачиваем обёртки таблиц, ряд → абзац, ячейку → inline с разделителем —
    остаётся только текст с сохранённой структурой строк.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["table", "tbody", "thead", "tfoot"]):
        tag.unwrap()
    for row in soup.find_all("tr"):
        row.name = "p"
    for cell in soup.find_all(["td", "th"]):
        cell.append(" ")  # разделитель между ячейками ряда
        cell.name = "span"
    return str(soup)


def _clean_markdown(text: str) -> str:
    """Убирает zero-width спейсеры, nbsp и схлопывает лишние пробелы/пустые строки."""
    text = text.translate(_ZERO_WIDTH_MAP).replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _html_to_markdown(html: str) -> str:
    """HTML-тело письма → markdown для модели.

    Расплющиваем layout-таблицы (см. _flatten_html_tables), выкидываем картинки
    (трекинг-пиксели и base64-data-URI раздувают контекст), затем чистим мусор
    (см. _clean_markdown).
    """
    if not html:
        return ""
    try:
        text = _md(_flatten_html_tables(html), strip=["img"], heading_style="ATX")
    except Exception:  # noqa: BLE001 — на битой вёрстке падать не должны
        return ""
    return _clean_markdown(text)


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
    email_addr: str,
    token: str,
    folder: str,
    message_id: str,
    include_html: bool = False,
) -> dict[str, Any]:
    conn = _connect(email_addr, token)
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, msg_data = conn.fetch(message_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            return {"error": f"Письмо {message_id} не найдено в папке {folder}."}
        msg = email.message_from_bytes(msg_data[0][1])
        # Тело для модели: HTML → markdown ДО обрезки (сохраняет структуру/ссылки),
        # с фолбэком на text/plain, если HTML-части нет или конвертация не удалась.
        html = _extract_html(msg)
        body = (_html_to_markdown(html) or _extract_text(msg)).strip()
        truncated = len(body) > MAX_BODY_CHARS
        if truncated:
            body = body[:MAX_BODY_CHARS] + "…"
        result: dict[str, Any] = {
            "id": message_id,
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "subject": _decode(msg.get("Subject")),
            "date": msg.get("Date"),
            "body": body,
            "truncated": truncated,
        }
        # include_html — «нормальное» чтение: отдаём и сырой HTML (виджету / когда
        # модели явно нужна исходная вёрстка).
        if include_html and html:
            result["html"] = html[:MAX_HTML_CHARS]
        return result
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


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
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
    return build_widget_tool_message(
        with_widget_note(inbox_payload(folder, items), runtime), runtime=runtime
    )


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def mail_read(
    runtime: ToolRuntime,
    message_id: str,
    folder: str = "INBOX",
    include_html: bool = False,
) -> dict[str, Any]:
    """Читает письмо Яндекс.Почты целиком (текст, обрезается при необходимости).

    Тело письма отдаётся как markdown (HTML-вёрстка конвертируется), обычно этого
    достаточно. Ставь include_html=True, только если нужна исходная HTML-вёрстка.

    Args:
        message_id: Идентификатор письма (поле id из mail_search).
        folder: Папка, в которой лежит письмо (по умолчанию "INBOX").
        include_html: Добавить в ответ исходный HTML письма (по умолчанию False).
    """
    email_addr, token = await get_mail_auth(runtime)
    return await asyncio.to_thread(
        _read_sync, email_addr, token, folder, message_id, include_html
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


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.ALWAYS,
    ),
)
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
    return await asyncio.to_thread(_send_sync, email_addr, token, to, subject, body)
