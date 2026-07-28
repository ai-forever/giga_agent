from __future__ import annotations

from typing import Annotated

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.logging import get_logger
from giga_agent.memory.runtime import (
    build_memory_service,
    get_memory_show_global,
    get_memory_tags,
    is_memory_disabled,
)
from giga_agent.memory.service import SEARCH_DEFAULT_N


logger = get_logger(__name__)


def _command(*, runtime: ToolRuntime, content: str, is_error: bool = False) -> Command:
    kwargs = {
        "tool_call_id": runtime.tool_call_id,
        "content": content,
        "name": "search_memories",
        "additional_kwargs": {"tool_name": "search_memories"},
    }
    if is_error:
        kwargs["status"] = "error"
    return Command(update={"messages": [ToolMessage(**kwargs)]})


@tool(
    description=(
        "Семантический поиск по файлам памяти пользователя. "
        "Возвращает top-N релевантных фрагментов с путём, цитатой и оценкой."
    ),
    extras=tool_extras(
        ToolEffect.READ,
        repl_skip=True,
        not_compress=True,
        not_process=True,
    ),
)
async def search_memories(
    query: Annotated[str, "Запрос для поиска по памяти"],
    runtime: ToolRuntime,
    n: Annotated[int, "Сколько фрагментов вернуть (1..20)"] = SEARCH_DEFAULT_N,
) -> Command:
    if runtime is None:
        return _command(
            runtime=runtime, content="Ошибка: ToolRuntime is required", is_error=True
        )
    if is_memory_disabled(runtime.config):
        return _command(
            runtime=runtime,
            content="Память отключена в текущем контексте (memory_disabled=True).",
            is_error=True,
        )

    if not isinstance(query, str) or not query.strip():
        return _command(
            runtime=runtime,
            content="Ошибка: query пустой.",
            is_error=True,
        )

    n = max(1, min(int(n or SEARCH_DEFAULT_N), 20))

    try:
        service = await build_memory_service(runtime.config)
    except Exception as exc:
        logger.exception("Failed to build MemoryService for search_memories")
        return _command(
            runtime=runtime,
            content=f"Ошибка: не удалось инициализировать память — {exc}",
            is_error=True,
        )

    if not service.has_embeddings:
        return _command(
            runtime=runtime,
            content=(
                "Семантический поиск недоступен: embedding-модель не настроена. "
                "Используй read_file для прямого чтения файлов памяти."
            ),
            is_error=True,
        )

    tags = get_memory_tags(runtime.config)
    show_global = get_memory_show_global(runtime.config, tags=tags)

    try:
        hits = await service.search(
            query,
            n=n,
            visible_tags=tags or None,
            include_global=show_global,
        )
    except Exception as exc:
        logger.exception("search_memories failed")
        return _command(
            runtime=runtime,
            content=f"Ошибка поиска: {exc}",
            is_error=True,
        )

    if not hits:
        return _command(
            runtime=runtime,
            content="По запросу ничего не нашлось.",
        )

    lines: list[str] = []
    for i, hit in enumerate(hits, start=1):
        lines.append(f"[{i}] {hit.path} (score: {hit.score:.3f})")
        snippet = hit.snippet.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        lines.append(f"    {snippet}")
    return _command(runtime=runtime, content="\n".join(lines))


__all__ = ["search_memories"]
