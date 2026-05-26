from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from giga_agent.core.logging import get_logger
from giga_agent.memory.backends.base import (
    MemoryFileExistsError,
    MemoryFileNotFoundError,
)
from giga_agent.memory.paths import (
    InvalidMemoryPathError,
    ParsedMemoryPath,
    global_about_path,
    is_about_file,
    is_memory_path,
    parse_memory_path,
    tagged_about_path,
)
from giga_agent.memory.runtime import (
    build_memory_service,
    get_memory_show_global,
    get_memory_tags,
    is_memory_disabled,
)
from giga_agent.memory.service import (
    MAX_MEMORY_FILE_LINES,
    MemoryFileTooLargeError,
)


logger = get_logger(__name__)


ABOUT_GLOBAL_TEMPLATE = (
    "# ABOUT\n"
    "Здесь хранится информация о пользователе. Записывай сюда то, что должен "
    "помнить о собеседнике: имя, роль, привычки, контекст работы, "
    "предпочтения по стилю общения.\n\n"
    "Файл пуст. Дополняй его по мере появления информации через write_file/edit_file.\n"
)


ABOUT_TAGGED_TEMPLATE = (
    "# ABOUT (tag: {tag})\n"
    "Информация про текущий чат/контекст ({tag}): кто здесь, зачем, что обсуждается.\n\n"
    "Файл пуст. Дополняй его по мере появления информации.\n"
)


def _is_memory_path(file_path: str) -> bool:
    return is_memory_path(file_path)


def _build_command(
    *,
    runtime: ToolRuntime,
    tool_name: str,
    content: str,
    is_error: bool = False,
) -> Command:
    tool_message_kwargs: dict[str, Any] = {
        "tool_call_id": runtime.tool_call_id,
        "content": content,
        "name": tool_name,
        "additional_kwargs": {"tool_name": tool_name},
    }
    if is_error:
        tool_message_kwargs["status"] = "error"
    return Command(update={"messages": [ToolMessage(**tool_message_kwargs)]})


def _check_visibility(
    parsed: ParsedMemoryPath,
    *,
    tags: list[str],
    show_global: bool,
) -> str | None:
    """Return an error message if path is not accessible under current scope."""
    if parsed.tag is None:
        if not show_global:
            return (
                "Глобальные файлы памяти скрыты в текущем контексте. "
                f"Доступные теги: {tags or '(нет)'}. Пиши под тегом, "
                f"например /memories/{tags[0]}/<file>.md."
                if tags
                else "Глобальные файлы памяти скрыты в текущем контексте, "
                "а доступные теги отсутствуют — память недоступна."
            )
        return None

    if parsed.tag not in tags:
        return (
            f"Файл {parsed.path} помечен тегом {parsed.tag!r}, которого нет "
            f"в текущей области видимости. Доступные теги: {tags or '(нет)'}."
        )
    return None


def _about_template(parsed: ParsedMemoryPath) -> str:
    if parsed.tag is None:
        return ABOUT_GLOBAL_TEMPLATE
    return ABOUT_TAGGED_TEMPLATE.format(tag=parsed.tag)


async def _memory_read(file_path: str, runtime: ToolRuntime) -> Command:
    config = runtime.config
    if is_memory_disabled(config):
        return _build_command(
            runtime=runtime,
            tool_name="read_file",
            content="Память отключена в текущем контексте (memory_disabled=True).",
            is_error=True,
        )

    try:
        parsed = parse_memory_path(file_path)
    except InvalidMemoryPathError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="read_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )

    tags = get_memory_tags(config)
    show_global = get_memory_show_global(config, tags=tags)
    err = _check_visibility(parsed, tags=tags, show_global=show_global)
    if err:
        return _build_command(
            runtime=runtime, tool_name="read_file", content=err, is_error=True
        )

    service = await build_memory_service(config, include_fast_llm=False)
    file = await service.get(file_path)
    if file is None:
        if is_about_file(parsed):
            template = _about_template(parsed)
            return _build_command(
                runtime=runtime,
                tool_name="read_file",
                content=(
                    f"Файл: {file_path}\n----\n"
                    + _format_with_line_numbers(template)
                    + "\n----\n"
                    + "Файл памяти ABOUT ещё не создан. Это шаблон — "
                    + "первое write_file сохранит твою версию."
                ),
            )
        return _build_command(
            runtime=runtime,
            tool_name="read_file",
            content=f"Ошибка: Файл памяти не найден ({file_path}).",
            is_error=True,
        )

    return _build_command(
        runtime=runtime,
        tool_name="read_file",
        content=(
            f"Файл: {file_path}\n----\n"
            + _format_with_line_numbers(file.content)
            + "\n----"
        ),
    )


def _format_with_line_numbers(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return "File is empty."
    return "\n".join(f"{i:>6}|{line}" for i, line in enumerate(lines, start=1))


async def _memory_write(
    file_path: str, content: str, runtime: ToolRuntime
) -> Command:
    config = runtime.config
    if is_memory_disabled(config):
        return _build_command(
            runtime=runtime,
            tool_name="write_file",
            content="Память отключена в текущем контексте (memory_disabled=True).",
            is_error=True,
        )

    try:
        parsed = parse_memory_path(file_path)
    except InvalidMemoryPathError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="write_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )

    tags = get_memory_tags(config)
    show_global = get_memory_show_global(config, tags=tags)
    err = _check_visibility(parsed, tags=tags, show_global=show_global)
    if err:
        return _build_command(
            runtime=runtime, tool_name="write_file", content=err, is_error=True
        )

    service = await build_memory_service(config)
    try:
        result = await service.create(path=file_path, content=content)
    except MemoryFileTooLargeError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="write_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )
    except MemoryFileExistsError:
        return _build_command(
            runtime=runtime,
            tool_name="write_file",
            content=(
                f"Ошибка: Файл памяти уже существует ({file_path}). "
                "Используй edit_file для изменения."
            ),
            is_error=True,
        )

    msg = f"Файл памяти создан: {file_path}"
    if result.description_repaired:
        msg += (
            "\n<memory-warning>Description в frontmatter не был указан "
            "корректно — сгенерирован автоматически: "
            f"{result.repaired_description!r}. Проверь и поправь "
            "при необходимости.</memory-warning>"
        )
    return _build_command(runtime=runtime, tool_name="write_file", content=msg)


async def _memory_edit(
    file_path: str,
    find_string: str,
    replace_string: str,
    replace_all: bool,
    runtime: ToolRuntime,
) -> Command:
    config = runtime.config
    if is_memory_disabled(config):
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content="Память отключена в текущем контексте (memory_disabled=True).",
            is_error=True,
        )

    try:
        parsed = parse_memory_path(file_path)
    except InvalidMemoryPathError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )

    tags = get_memory_tags(config)
    show_global = get_memory_show_global(config, tags=tags)
    err = _check_visibility(parsed, tags=tags, show_global=show_global)
    if err:
        return _build_command(
            runtime=runtime, tool_name="edit_file", content=err, is_error=True
        )

    if find_string == replace_string:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=(
                "Ошибка: find_string и replace_string совпадают. "
                f"Укажи разные значения. Файл: {file_path}"
            ),
            is_error=True,
        )

    service = await build_memory_service(config)
    existing = await service.get(file_path)
    if existing is None:
        if is_about_file(parsed):
            existing_content = _about_template(parsed)
        else:
            return _build_command(
                runtime=runtime,
                tool_name="edit_file",
                content=(
                    f"Ошибка: Файл памяти не существует ({file_path}). "
                    "Используй write_file для создания."
                ),
                is_error=True,
            )
    else:
        existing_content = existing.content

    text = existing_content.replace("\r\n", "\n").replace("\r", "\n")
    find_string = find_string.replace("\r\n", "\n").replace("\r", "\n")
    replace_string = replace_string.replace("\r\n", "\n").replace("\r", "\n")

    count = text.count(find_string)
    if count == 0:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=(
                f"Ошибка: find_string не найден в файле памяти {file_path}. "
                "Перечитай файл через read_file, сверь содержимое и попробуй снова."
            ),
            is_error=True,
        )
    if not replace_all and count > 1:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=(
                f"Ошибка: find_string не уникален, найдено {count} вхождений "
                f"в {file_path}. Передай более длинный фрагмент или используй "
                "replace_all=True."
            ),
            is_error=True,
        )

    if replace_all:
        new_text = text.replace(find_string, replace_string)
        replacements = count
    else:
        new_text = text.replace(find_string, replace_string, 1)
        replacements = 1

    try:
        if existing is None:
            result = await service.create(path=file_path, content=new_text)
        else:
            result = await service.update(path=file_path, content=new_text)
    except MemoryFileTooLargeError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )
    except MemoryFileNotFoundError:
        return _build_command(
            runtime=runtime,
            tool_name="edit_file",
            content=(
                f"Ошибка: Файл памяти не существует ({file_path}). "
                "Используй write_file для создания."
            ),
            is_error=True,
        )

    msg = f"Файл памяти отредактирован: {file_path}, замен: {replacements}"
    if result.description_repaired:
        msg += (
            "\n<memory-warning>Description в frontmatter не был указан "
            "корректно — сгенерирован автоматически: "
            f"{result.repaired_description!r}. Проверь и поправь "
            "при необходимости.</memory-warning>"
        )
    return _build_command(runtime=runtime, tool_name="edit_file", content=msg)


async def _memory_delete(file_path: str, runtime: ToolRuntime) -> Command:
    config = runtime.config
    if is_memory_disabled(config):
        return _build_command(
            runtime=runtime,
            tool_name="delete_file",
            content="Память отключена в текущем контексте (memory_disabled=True).",
            is_error=True,
        )

    try:
        parsed = parse_memory_path(file_path)
    except InvalidMemoryPathError as exc:
        return _build_command(
            runtime=runtime,
            tool_name="delete_file",
            content=f"Ошибка: {exc}",
            is_error=True,
        )

    tags = get_memory_tags(config)
    show_global = get_memory_show_global(config, tags=tags)
    err = _check_visibility(parsed, tags=tags, show_global=show_global)
    if err:
        return _build_command(
            runtime=runtime, tool_name="delete_file", content=err, is_error=True
        )

    service = await build_memory_service(config, include_fast_llm=False)
    removed = await service.delete(path=file_path)
    if not removed:
        return _build_command(
            runtime=runtime,
            tool_name="delete_file",
            content=f"Ошибка: Файл памяти не найден ({file_path}).",
            is_error=True,
        )
    return _build_command(
        runtime=runtime,
        tool_name="delete_file",
        content=f"Файл памяти удалён: {file_path}",
    )


__all__ = [
    "_is_memory_path",
    "_memory_read",
    "_memory_write",
    "_memory_edit",
    "_memory_delete",
    "MAX_MEMORY_FILE_LINES",
    "ABOUT_GLOBAL_TEMPLATE",
    "ABOUT_TAGGED_TEMPLATE",
    "global_about_path",
    "tagged_about_path",
]
