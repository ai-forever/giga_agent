"""Channel-agnostic rendering of an agent run result into deliverable parts.

A "part" is ``{"kind": "text" | "image_url" | "attachment_path", "value": str}``.
Channels interpret these parts when delivering (e.g. Telegram sends text as
MarkdownV2, images as photos, attachment paths downloaded from the sandbox).
"""

from __future__ import annotations

from typing import Any

from giga_agent.channels.telegram.utils import (
    _extract_ai_response,
    _extract_text_media,
)


def render_run_result(result: dict[str, Any]) -> list[dict[str, str]]:
    """Extract the final AI answer from a graph run and split it into parts."""
    response_text, image_urls = _extract_ai_response(result)
    parts: list[dict[str, str]] = list(_extract_text_media(response_text))
    parts.extend({"kind": "image_url", "value": url} for url in image_urls if url)
    return parts
