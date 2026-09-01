"""Подсказка модели для тулов Яндекс-интеграций, отдающих виджеты.

В вебе виджет виден пользователю прямо в чате — данные уже перед ним, поэтому
пересказывать содержимое результата текстом не нужно. В канальных чатах
(Telegram) виджеты не рендерятся, значит там результат надо пересказать —
подсказку не добавляем. Логика живёт в слое интеграций (а не в общем
build_widget_tool_message), т.к. касается только этих тулов.
"""

from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime

from giga_agent.utils.thread_metadata import (
    get_thread_id_from_config,
    get_thread_metadata,
)

WIDGET_SHOWN_NOTE = (
    "Эти данные уже показаны пользователю виджетом в интерфейсе. "
    "Не пересказывай их содержимое текстом — дай только короткий комментарий, "
    "если он действительно полезен."
)


async def _renders_widget_inline(runtime: ToolRuntime) -> bool:
    """True, если виджет виден пользователю прямо в чате (веб-интерфейс)."""
    config = getattr(runtime, "config", None)
    metadata = await get_thread_metadata(config, get_thread_id_from_config(config))
    return metadata.get("channel") != "telegram"


async def with_widget_note(
    payload: dict[str, Any], runtime: ToolRuntime
) -> dict[str, Any]:
    """Добавляет в payload подсказку 'не пересказывай', если ран вне Telegram."""
    if await _renders_widget_inline(runtime):
        return {**payload, "note": WIDGET_SHOWN_NOTE}
    return payload
