from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.agent.types import AgentState
from giga_agent.core.logging import get_logger
from giga_agent.core.module import BaseModule
from giga_agent.memory.events import ensure_subscribed
from giga_agent.memory.middleware import MemoryMiddleware
from giga_agent.memory.paths import (
    is_about_file,
    parse_memory_path,
)
from giga_agent.memory.runtime import (
    build_memory_service,
    get_memory_show_global,
    get_memory_tags,
    is_memory_disabled,
)
from giga_agent.memory.tool import search_memories
from giga_agent.models.users import UserShort
from giga_agent.modules.io.memory_bridge import (
    ABOUT_GLOBAL_TEMPLATE,
)


logger = get_logger(__name__)


GLOBAL_FULL_CONTENT_BUDGET = 8000  # chars; bigger files go into the index only


class MemoryModule(BaseModule):
    id: str = "memory"

    async def _has_embeddings(self, user: UserShort | None, *, config) -> bool:
        if config is None:
            return False
        try:
            resolver = RuntimeResolver.from_config(config)
        except ValueError:
            try:
                resolver = await RuntimeResolver.create(config)
                resolver.inject(config)
            except Exception:
                return False
        return resolver.has_embedding

    async def get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config=None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        _ = user, agent, kwargs
        if config is None:
            return []
        if is_memory_disabled(config):
            return []
        if not await self._has_embeddings(user, config=config):
            return []
        return [search_memories]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = user, agent, state, kwargs
        if config is None:
            return None
        if is_memory_disabled(config):
            return None

        tags = get_memory_tags(config)
        show_global = get_memory_show_global(config, tags=tags)

        try:
            service = await build_memory_service(config, include_fast_llm=False)
        except Exception:
            logger.exception("MemoryModule.get_instructions: build failed")
            return None

        try:
            files = await service.list_visible(
                visible_tags=tags or None,
                include_global=show_global,
            )
        except Exception:
            logger.exception("MemoryModule.get_instructions: list failed")
            return None

        return _render_memory_block(
            files=files,
            tags=tags,
            show_global=show_global,
            has_search=service.has_embeddings,
        )

    def get_middleware(self, **kwargs: Any) -> AgentMiddleware:
        _ = kwargs
        return MemoryMiddleware()

    def get_api_router(self, **kwargs: Any) -> APIRouter:
        _ = kwargs
        from giga_agent.memory.api import router

        return router

    async def on_startup(self, session, **kwargs: Any) -> None:
        _ = session, kwargs
        await ensure_subscribed()


def _render_memory_block(
    *,
    files,
    tags: list[str],
    show_global: bool,
    has_search: bool,
) -> str:
    parts: list[str] = []
    parts.append("<memory>")
    parts.append(
        "Память пользователя. Используй её, чтобы не переспрашивать одно и то же, "
        "и активно обновляй (write_file/edit_file по путям /memories/...)."
    )
    if has_search:
        parts.append("Для семантического поиска по памяти есть тул search_memories.")
    parts.append(
        "Каждый файл памяти кроме ABOUT.md должен иметь YAML-frontmatter с полем "
        "`description:` (одна строка, ≤200 символов). "
        "Лимит размера файла памяти — 200 строк."
    )

    by_tag: dict[str | None, list] = {}
    for f in files:
        by_tag.setdefault(f.tag, []).append(f)

    global_about = None
    tagged_abouts: list = []
    other_global: list = []
    other_tagged: list = []

    for tag, group in by_tag.items():
        for f in group:
            parsed = parse_memory_path(f.path)
            if is_about_file(parsed):
                if tag is None:
                    global_about = f
                else:
                    tagged_abouts.append(f)
            else:
                if tag is None:
                    other_global.append(f)
                else:
                    other_tagged.append(f)

    if show_global:
        if global_about is not None:
            parts.append("<about>")
            parts.append(global_about.content.strip())
            parts.append("</about>")
        else:
            parts.append("<about>")
            parts.append(ABOUT_GLOBAL_TEMPLATE.strip())
            parts.append("</about>")

    for f in tagged_abouts:
        parts.append(f'<about tag="{f.tag}">')
        parts.append(f.content.strip())
        parts.append("</about>")

    # Files under visible tags — always shown in full.
    for f in other_tagged:
        parts.append(
            f'<file path="{f.path}" description="{(f.description or "").strip()}">'
        )
        parts.append(f.content.strip())
        parts.append("</file>")

    # Global non-ABOUT files: full content if budget allows, otherwise index.
    inline_global: list = []
    indexed_global: list = []
    if show_global:
        budget = GLOBAL_FULL_CONTENT_BUDGET
        for f in other_global:
            size = len(f.content)
            if size <= budget:
                inline_global.append(f)
                budget -= size
            else:
                indexed_global.append(f)

    for f in inline_global:
        parts.append(
            f'<file path="{f.path}" description="{(f.description or "").strip()}">'
        )
        parts.append(f.content.strip())
        parts.append("</file>")

    if indexed_global:
        parts.append("<index>")
        for f in indexed_global:
            desc = (f.description or "(без описания)").strip()
            parts.append(f"- {f.path} — {desc}")
        parts.append("</index>")

    parts.append("</memory>")
    return "\n".join(parts)


__all__ = ["MemoryModule"]
