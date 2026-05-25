"""Deep research module — plan → search → read → reflect → compose."""
from __future__ import annotations

from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.deep_research.graph import run_deep_research

DEEP_RESEARCH_INSTRUCTIONS = """- **run_deep_research** — Проводит глубокое исследование: декомпозирует запрос на подвопросы, ищет и читает несколько веб-источников, собирает markdown-отчёт с нумерованными цитатами.
Используй для сложных вопросов, где нужен сбор и синтез из нескольких источников (обзоры, сравнения, текущее состояние темы/рынка/технологии).
Для простых поисковых вопросов используй search.

ВАЖНО: перед вызовом `run_deep_research` ОБЯЗАТЕЛЬНО напиши пользователю одну короткую строку-прелюдию (например: «Запускаю глубокое исследование — займёт 1–2 минуты.»), чтобы он понимал, что идёт длинный процесс. После этого вызывай инструмент."""


class DeepResearchModule(BaseModule):
    id: str = "deep_research"
    label: str = "Deep Research"
    description: str = "Глубокое исследование: план → поиск → чтение → синтез отчёта"
    icon: str = "BookOpen"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if user is None:
            return False
        return user.llm_id is not None and user.search_engine_id is not None

    def get_subgraphs(self, **kwargs: Any) -> dict[str, str]:
        _ = kwargs
        return {
            "deep_research": "giga_agent.modules.deep_research.graph:graph",
        }

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config=None,
        **kwargs
    ) -> List[BaseTool]:
        _ = agent
        if user is None:
            return []
        if user.llm_id is None or user.search_engine_id is None:
            return []
        return [run_deep_research]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, kwargs
        if user is None or user.llm_id is None or user.search_engine_id is None:
            return None
        return DEEP_RESEARCH_INSTRUCTIONS
