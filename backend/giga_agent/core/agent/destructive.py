"""Реестр деструктивных инструментов.

Деструктивные тулы требуют подтверждения пользователя ВСЕГДА — даже в
автономном режиме (auto-approve). Это реализовано в ToolResultMiddleware:
для таких вызовов поднимается interrupt типа "confirm_destructive", который
фронт не авто-одобряет.
"""

from __future__ import annotations

# Явный список деструктивных тулов (имена). Модули могут пополнять при росте.
DESTRUCTIVE_TOOLS: set[str] = {
    "disk_delete",
    "mail_send",  # отправка письма необратима → подтверждение всегда
    "calendar_create_event",  # запись в календарь — подтверждение
    "calendar_delete_event",
}

# Соглашение по именам: всё, что удаляет/уничтожает данные.
_DESTRUCTIVE_SUFFIXES: tuple[str, ...] = ("_delete", "_remove", "_drop", "_purge")


def is_destructive(tool_name: str | None) -> bool:
    if not tool_name:
        return False
    if tool_name in DESTRUCTIVE_TOOLS:
        return True
    return any(tool_name.endswith(s) for s in _DESTRUCTIVE_SUFFIXES)
