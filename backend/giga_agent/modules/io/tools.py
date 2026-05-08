from __future__ import annotations

import asyncio
import io
import mimetypes
import re
import uuid
from typing import Annotated
from urllib.request import urlopen

from docx import Document as DocxDocument
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

MAX_READ_FILE_CHARS = 100_000
DEFAULT_READ_FILE_LIMIT = 1000
TABULAR_FILE_EXTENSIONS = frozenset(
    {
        ".csv",
        ".csv.gz",
        ".tsv",
        ".tsv.gz",
        ".xls",
        ".xlsx",
        ".xlsm",
        ".xlsb",
        ".ods",
        ".parquet",
        ".pq",
        ".feather",
        ".arrow",
        ".orc",
    }
)
TABULAR_MEDIA_TYPES = frozenset(
    {
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.ms-excel",
        "application/vnd.ms-excel.sheet.binary.macroenabled.12",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
        "application/vnd.apache.parquet",
        "application/x-parquet",
        "application/vnd.apache.arrow.file",
        "application/x-feather",
        "application/vnd.apache.orc",
    }
)


def _normalize_media_type(media_type: str | None) -> str:
    return (media_type or "").split(";", 1)[0].strip().lower()


def _is_tabular_file_reference(
    *,
    sandbox_path: str,
    file_name: str | None = None,
    media_type: str | None = None,
) -> bool:
    normalized_media_type = _normalize_media_type(media_type)
    if normalized_media_type in TABULAR_MEDIA_TYPES:
        return True

    for candidate in (sandbox_path, file_name):
        lower_candidate = (candidate or "").lower()
        if lower_candidate.endswith(tuple(TABULAR_FILE_EXTENSIONS)):
            return True

        guessed_media_type, _ = mimetypes.guess_type(lower_candidate)
        if _normalize_media_type(guessed_media_type) in TABULAR_MEDIA_TYPES:
            return True

    return False


def _build_tabular_read_hint(*, sandbox_path: str) -> str:
    return (
        f"Файл: {sandbox_path}\n"
        "Это похоже на табличные данные. read_file не читает такие файлы напрямую. "
        "Используй python tool и читай файл через подходящую библиотеку "
        "(например pandas, csv, openpyxl или pyarrow)."
    )


def _extract_pdf_text(data: bytes) -> str | None:
    from pdfminer.high_level import extract_text

    try:
        return extract_text(io.BytesIO(data))
    except Exception:
        return None


def _extract_docx_text(data: bytes) -> str | None:
    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception:
        return None

    text_parts: list[str] = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            text_parts.append(text)

    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            if row_text.strip():
                text_parts.append(row_text)

    return "\n\n".join(text_parts)


def _decode_text_bytes(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _text_from_file_bytes(
    *,
    data: bytes,
    sandbox_path: str,
    file_name: str | None = None,
    media_type: str | None = None,
) -> str | None:
    normalized_media_type = _normalize_media_type(media_type)
    lower_name = (file_name or "").lower()
    lower_path = sandbox_path.lower()

    if (
        normalized_media_type == "application/pdf"
        or lower_name.endswith(".pdf")
        or lower_path.endswith(".pdf")
        or data.startswith(b"%PDF-")
    ):
        return _extract_pdf_text(data)

    if (
        normalized_media_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or lower_name.endswith(".docx")
        or lower_path.endswith(".docx")
    ):
        return _extract_docx_text(data)

    return _decode_text_bytes(data)


async def _download_redirect_bytes(url: str) -> bytes:
    def _read_bytes() -> bytes:
        with urlopen(url, timeout=30.0) as response:
            return response.read()

    return await asyncio.to_thread(_read_bytes)


def _slice_lines(
    *,
    lines: list[str],
    offset: int | None,
    limit: int,
) -> tuple[list[str], int, int]:
    total_lines = len(lines)
    if offset is None:
        start_index = 0
    elif offset > 0:
        start_index = max(offset - 1, 0)
    else:
        start_index = max(total_lines + offset, 0)

    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    end_index = min(start_index + limit, total_lines)

    return lines[start_index:end_index], start_index, end_index


def _format_numbered_lines(
    *,
    lines: list[str],
    start_line_number: int,
    max_chars: int = MAX_READ_FILE_CHARS,
) -> tuple[str, int, bool]:
    parts: list[str] = []
    used_chars = 0
    returned_lines = 0

    for index, line in enumerate(lines, start=start_line_number):
        prefix = "" if not parts else "\n"
        formatted_line = f"{index:>6}|{line}"
        budget = max_chars - used_chars - len(prefix)
        if budget <= 0:
            return "".join(parts), returned_lines, True

        if len(formatted_line) > budget:
            if not parts:
                parts.append(prefix + formatted_line[:budget])
                returned_lines = 1
            return "".join(parts), returned_lines, True

        parts.append(prefix + formatted_line)
        used_chars += len(prefix) + len(formatted_line)
        returned_lines += 1

    return "".join(parts), returned_lines, False


def _build_next_read_hint(
    *,
    sandbox_path: str,
    total_lines: int,
    next_offset: int | None,
    remaining_lines: int,
    requested_limit: int | None,
    returned_lines: int,
    truncated_by_chars: bool,
) -> str:
    if total_lines == 0:
        return (
            "File is empty. Если хочешь перепроверить, вызови read_file с тем же "
            f"sandbox_path={sandbox_path!r}."
        )

    if remaining_lines <= 0 or next_offset is None:
        return (
            "Достигнут конец файла. Если нужно перечитать фрагмент, используй "
            f"read_file(sandbox_path={sandbox_path!r}, offset=1)."
        )

    next_limit = requested_limit or DEFAULT_READ_FILE_LIMIT
    char_limit_hint = ""
    if truncated_by_chars and returned_lines < next_limit:
        char_limit_hint = (
            f" Чтение файла ограничено лимитом в {MAX_READ_FILE_CHARS} символов, "
            "поэтому вернулось меньше строк, чем ты запрашивал."
        )

    return (
        f"Файл еще имеет {remaining_lines} строк после текущего фрагмента. "
        f"{char_limit_hint}"
        f"Чтобы продолжить, лучше вызвать "
        f"read_file(sandbox_path={sandbox_path!r}, offset={next_offset}, limit={next_limit})."
    )


async def _get_owner_id(runtime: ToolRuntime) -> uuid.UUID:
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


def _build_io_command(
    *,
    runtime: ToolRuntime,
    tool_name: str,
    content: str,
) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    tool_call_id=runtime.tool_call_id,
                    content=content,
                    additional_kwargs={"tool_name": tool_name},
                )
            ]
        }
    )


async def _read_file_text(
    sandbox_path: str,
    owner_id: uuid.UUID,
) -> str:
    """Прочитать файл целиком как текст. Поднимает исключение при ошибке."""
    from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
    from giga_agent.sandbox.manager import SandboxManager

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        _, result = await manager.read_file_by_path_for_user(
            user_id=owner_id,
            sandbox_path=sandbox_path,
        )

    if isinstance(result, ContentResult):
        data = result.data
    elif isinstance(result, StreamResult):
        chunks = []
        async for chunk in result.stream:
            chunks.append(chunk)
        data = b"".join(chunks)
    elif isinstance(result, RedirectResult):
        data = await _download_redirect_bytes(result.url)
    else:
        raise ValueError("Файл доступен только по URL, прямое чтение невозможно")

    text = data.decode("utf-8")
    return text


@tool(
    description="""Читает файл из файловой системы. Ты можешь получить доступ к любому файлу напрямую с помощью этого инструмента.
Если пользователь передаёт путь к файлу, считай этот путь валидным. Если файл не существует, будет возвращена ошибка.
Использование:
- Можно опционально указать offset и limit по строкам, что особенно удобно для длинных файлов, но по умолчанию читаются первые 1000 строк файла. Чтобы читать его дальше повышай offset и читай файл дальше.
- Строки в результате нумеруются начиная с 1 в формате: НОМЕР_СТРОКИ|СОДЕРЖИМОЕ_СТРОКИ
- Если файл существует, но пустой, инструмент вернёт 'File is empty.'
- Табличные файлы (например CSV, TSV, Excel, ODS, Parquet, Arrow, Feather, ORC) нужно читать через python tool, а не через read_file.
- PDF и DOCX-файлы автоматически конвертируются в текст (с теми же ограничениями на размер ответа, что и для остальных файлов).""",
    extras={"repl_skip": True, "not_compress": True, "not_process": True},
)
async def read_file(
    sandbox_path: Annotated[
        str, "Путь к файлу в sandbox (sandbox_path из результата get_documents)"
    ],
    runtime: ToolRuntime,
    offset: Annotated[
        int,
        "Номер строки для начала чтения: положительные значения 1-indexed, отрицательные считаются от конца файла",
    ] = 1,
    limit: Annotated[
        int,
        "Количество строк для чтения. Если не передано, инструмент пытается вернуть файл целиком в пределах лимита размера ответа",
    ] = 1000,
) -> Command:
    """Читает файл из sandbox построчно с поддержкой offset/limit."""
    from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
    from giga_agent.sandbox.manager import SandboxManager

    def _result(text: str) -> Command:
        return _build_io_command(runtime=runtime, tool_name="read_file", content=text)

    if runtime is None:
        return _result("Ошибка: ToolRuntime is required")

    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    if _is_tabular_file_reference(sandbox_path=sandbox_path):
        return _result(_build_tabular_read_hint(sandbox_path=sandbox_path))

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        try:
            file_record, result = await manager.read_file_by_path_for_user(
                user_id=owner_id,
                sandbox_path=sandbox_path,
            )
        except Exception as e:
            logger.warning("read_file failed for %s: %s", sandbox_path, e)
            return _result(f"Ошибка: {e}")

    if _is_tabular_file_reference(
        sandbox_path=sandbox_path,
        file_name=file_record.original_name,
    ):
        return _result(_build_tabular_read_hint(sandbox_path=sandbox_path))

    text: str | None
    if isinstance(result, ContentResult):
        if _is_tabular_file_reference(
            sandbox_path=sandbox_path,
            file_name=file_record.original_name,
            media_type=result.media_type,
        ):
            return _result(_build_tabular_read_hint(sandbox_path=sandbox_path))

        text = _text_from_file_bytes(
            data=result.data,
            sandbox_path=sandbox_path,
            file_name=file_record.original_name,
            media_type=result.media_type,
        )
        if text is None:
            return _result(f"Ошибка: Файл не является текстовым (бинарный формат). Файл: {file_record.original_name}, размер: {file_record.size}")
    elif isinstance(result, StreamResult):
        chunks = []
        async for chunk in result.stream:
            chunks.append(chunk)
        data = b"".join(chunks)
        if _is_tabular_file_reference(
            sandbox_path=sandbox_path,
            file_name=file_record.original_name,
            media_type=result.media_type,
        ):
            return _result(_build_tabular_read_hint(sandbox_path=sandbox_path))

        text = _text_from_file_bytes(
            data=data,
            sandbox_path=sandbox_path,
            file_name=file_record.original_name,
            media_type=result.media_type,
        )
        if text is None:
            return _result(f"Ошибка: Файл не является текстовым (бинарный формат). Файл: {file_record.original_name}, размер: {file_record.size}")
    elif isinstance(result, RedirectResult):
        try:
            data = await _download_redirect_bytes(result.url)
        except Exception as e:
            logger.warning(
                "read_file redirect download failed for %s: %s", sandbox_path, e
            )
            return _result(f"Ошибка: {e}")
        text = _text_from_file_bytes(
            data=data,
            sandbox_path=sandbox_path,
            file_name=file_record.original_name,
        )
        if text is None:
            return _result(f"Ошибка: Файл не является текстовым (бинарный формат). Файл: {file_record.original_name}, размер: {file_record.size}")
    else:
        return _result("Ошибка: Файл доступен только по URL, прямое чтение невозможно")

    if text == "":
        hint = _build_next_read_hint(
            sandbox_path=sandbox_path,
            total_lines=0,
            next_offset=None,
            remaining_lines=0,
            requested_limit=limit,
            returned_lines=0,
            truncated_by_chars=False,
        )
        return _result(f"Файл: {sandbox_path}\nFile is empty.\n{hint}")

    lines = text.splitlines()
    try:
        selected_lines, start_index, _ = _slice_lines(
            lines=lines,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        return _result(f"Ошибка: {e}")

    content, returned_lines, truncated_by_chars = _format_numbered_lines(
        lines=selected_lines,
        start_line_number=start_index + 1,
    )
    remaining_lines = max(len(lines) - (start_index + returned_lines), 0)
    next_offset = start_index + returned_lines + 1 if remaining_lines > 0 else None

    return _result(
        f"Файл: {sandbox_path}\n----\n" + content + "\n----\n" + _build_next_read_hint(
            sandbox_path=sandbox_path,
            total_lines=len(lines),
            next_offset=next_offset,
            remaining_lines=remaining_lines,
            requested_limit=limit,
            returned_lines=returned_lines,
            truncated_by_chars=truncated_by_chars,
        )
    )


@tool(
    description="""Создаёт новый файл в файловой системе.

Использование:
- Инструмент write_file создаёт новый файл. Если файл по указанному пути уже существует, будет возвращена ошибка.
- Предпочитай редактирование существующих файлов (через edit_file) созданию новых, когда это возможно.""",
    extras={"repl_skip": True, "not_compress": True, "not_process": True},
)
async def write_file(
    file_path: Annotated[
        str,
        "Абсолютный путь для создания файла. Должен быть абсолютным, не относительным.",
    ],
    content: Annotated[
        str,
        "Текстовое содержимое для записи в файл. Этот параметр обязателен.",
    ],
    runtime: ToolRuntime,
) -> Command:
    """Создаёт новый файл по указанному пути."""
    from giga_agent.sandbox.manager import SandboxManager

    def _result(text: str) -> Command:
        return _build_io_command(runtime=runtime, tool_name="write_file", content=text)

    if runtime is None:
        return _result("Ошибка: ToolRuntime is required")

    owner_id = await _get_owner_id(runtime)

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        try:
            exists = await manager.file_exists_for_user(
                user_id=owner_id,
                sandbox_path=file_path,
            )
        except Exception as e:
            logger.warning(
                "write_file file_exists check failed for %s: %s", file_path, e
            )
            return _result(f"Ошибка: {e}")

        if exists:
            return _result(f"Ошибка: Файл уже существует ({file_path}). Используй edit_file для изменения существующих файлов.")

        content_bytes = content.encode("utf-8")
        try:
            await manager.write_file_content_for_user(
                user_id=owner_id,
                sandbox_path=file_path,
                content=content_bytes,
            )
        except Exception as e:
            logger.warning("write_file failed for %s: %s", file_path, e)
            return _result(f"Ошибка: {e}")

    return _result(f"Файл создан: {file_path}, размер: {len(content_bytes)} байт")


_FILE_MUTATING_TOOLS = frozenset({"edit_file", "write_file", "shell"})


def _has_recent_read_file(messages: list, file_path: str, lookback: int = 2) -> bool:
    """Return True if a recent read_file call targeted *file_path*.

    Walks messages backwards, skipping the first AIMessage (the current
    edit_file call), and inspects up to *lookback* preceding AIMessages.
    If the nearest read_file invocation has ``sandbox_path`` equal to
    *file_path*, returns True.
    """
    skipped_first_ai = False
    ai_count = 0
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        if not skipped_first_ai:
            skipped_first_ai = True
            continue
        ai_count += 1
        if ai_count > lookback:
            break
        for tc in reversed(msg.tool_calls or []):
            name = tc.get("name", "")
            if name == "read_file":
                args = tc.get("args") or {}
                return args.get("sandbox_path", "") == file_path
    return False


@tool(
    description="""Выполняет точную замену строк в файлах.

Использование:
- Перед редактированием необходимо прочитать файл. Этот инструмент выдаст ошибку, если файл не существует.
- При редактировании сохраняй точные отступы (табы/пробелы) из вывода read_file. Никогда не включай префиксы номеров строк в find_string или replace_string.
- ВСЕГДА предпочитай редактирование существующих файлов созданию новых.""",
    extras={"repl_skip": True, "not_compress": True, "not_process": True},
)
async def edit_file(
    file_path: Annotated[
        str,
        "Абсолютный путь к редактируемому файлу. Должен быть абсолютным, не относительным.",
    ],
    find_string: Annotated[
        str,
        "Точный текст для поиска и замены. Должен быть уникальным в файле, если replace_all не True.",
    ],
    replace_string: Annotated[
        str,
        "Текст, на который заменяется find_string. Должен отличаться от find_string.",
    ],
    runtime: ToolRuntime,
    replace_all: Annotated[
        bool,
        "Если True, заменяет все вхождения find_string. Если False (по умолчанию), find_string должен быть уникальным.",
    ] = False,
) -> Command:
    """Выполняет точную замену строк в указанном файле."""
    from giga_agent.sandbox.manager import SandboxManager

    def _result(text: str) -> Command:
        return _build_io_command(runtime=runtime, tool_name="edit_file", content=text)

    if runtime is None:
        return _result("Ошибка: ToolRuntime is required")

    owner_id = await _get_owner_id(runtime)

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        try:
            exists = await manager.file_exists_for_user(
                user_id=owner_id,
                sandbox_path=file_path,
            )
        except Exception as e:
            logger.warning(
                "edit_file file_exists check failed for %s: %s", file_path, e
            )
            return _result(f"Ошибка: {e}")

        if not exists:
            return _result(f"Ошибка: Файл не существует ({file_path}). Используй write_file для создания новых файлов.")

    if find_string == replace_string:
        return _result(f"Ошибка: find_string и replace_string совпадают. Укажи разные значения. Файл: {file_path}")

    try:
        raw_text = await _read_file_text(sandbox_path=file_path, owner_id=owner_id)
    except Exception as e:
        logger.warning("edit_file read failed for %s: %s", file_path, e)
        return _result(f"Ошибка: {e}")

    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    find_string = find_string.replace("\r\n", "\n").replace("\r", "\n")
    replace_string = replace_string.replace("\r\n", "\n").replace("\r", "\n")

    count = text.count(find_string)
    if count == 0 and find_string.endswith("\n"):
        stripped = find_string[:-1]
        if text.endswith(stripped):
            find_string = stripped
            count = text.count(find_string)
    if count == 0:
        line_num_hint = ""
        if re.search(r"^\s{0,6}\d+\|", find_string, re.MULTILINE):
            line_num_hint = (
                " ВНИМАНИЕ: похоже, ты включил префиксы номеров строк "
                "(вида «  123|») из вывода read_file в find_string. "
                "Эти префиксы НЕ являются частью файла — убери их."
            )

        messages = runtime.state.get("messages", []) if runtime.state else []
        if _has_recent_read_file(messages, file_path):
            return _result(
                f"Ошибка: find_string не найден в файле {file_path}. "
                "Ты уже читал файл — ОБЯЗАТЕЛЬНО вызови think и внимательно сверь "
                "find_string с актуальным содержимым файла посимвольно (пробелы, "
                "отступы, переносы строк), прежде чем повторять попытку."
                + line_num_hint
            )
        return _result(
            f"Ошибка: find_string не найден в файле {file_path}. "
            "Перечитай файл через read_file и вызови think, чтобы внимательно сверить "
            "find_string с актуальным содержимым файла, прежде чем повторять попытку."
            + line_num_hint
        )

    if not replace_all and count > 1:
        return _result(
            f"Ошибка: find_string не уникален, найдено {count} вхождений в {file_path}. "
            "Передай более длинную строку с контекстом для уникальной идентификации, "
            "или используй replace_all=True для замены всех вхождений."
        )

    if replace_all:
        new_text = text.replace(find_string, replace_string)
        replacements = count
    else:
        new_text = text.replace(find_string, replace_string, 1)
        replacements = 1

    factory = await get_session_factory()
    async with factory() as session:
        manager = SandboxManager(session)
        try:
            await manager.write_file_content_for_user(
                user_id=owner_id,
                sandbox_path=file_path,
                content=new_text.encode("utf-8"),
            )
        except Exception as e:
            logger.warning("edit_file write failed for %s: %s", file_path, e)
            return _result(f"Ошибка: {e}")

    return _result(f"Файл отредактирован: {file_path}, замен: {replacements}")
