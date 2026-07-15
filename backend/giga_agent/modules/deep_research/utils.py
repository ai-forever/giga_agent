"""Helpers for deep_research."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "yclid",
    "_ga",
    "ref",
    "ref_src",
}


# Домены, которые системно не отдают полезный markdown через Jina Reader:
# - auth-walls (vk/facebook/instagram/twitter) — Jina получает login-стабы
# - video-first (youtube) — нечего конвертировать в текст
# - форумы с anti-bot (yaplakal) — 403 через Jina
# - reddit без авторизации часто блокируется
# Проверяется по суффиксу хоста (т.е. m.vk.com, www.vk.com — тоже блок).
BLOCKED_DOMAIN_SUFFIXES = {
    "vk.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "t.me",
    "telegram.org",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "yaplakal.com",
    "reddit.com",
    "flickr.com",
}


def is_blocked_domain(url: str) -> bool:
    """True, если хост URL попадает под блоклист (точное совпадение или поддомен)."""
    if not url:
        return False
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    if not host:
        return False
    for suffix in BLOCKED_DOMAIN_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def normalize_url(url: str) -> str:
    """Убирает tracking-параметры и фрагмент для дедупликации."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QUERY_KEYS
    ]
    cleaned = parsed._replace(query=urlencode(query_pairs), fragment="")
    return urlunparse(cleaned).rstrip("/")


def dedup_sources(sources: Iterable[dict]) -> list[dict]:
    """Убирает дубли по нормализованному URL, сохраняя первое вхождение."""
    seen: set[str] = set()
    out: list[dict] = []
    for src in sources:
        key = normalize_url(src.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(src)
    return out
