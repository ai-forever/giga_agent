"""Reflect node — оценка покрытия и решение loop/stop.

LLM со structured output:
- coverage[sub_q_id] → "covered" | "gap"
- new_queries_by_sub → доп. поисковые запросы для gap-подвопросов
- stop → если >=80% covered, LLM сам ставит stop=True

Роутер (`route_after_reflect`) выходит в compose по любому из условий:
`stop=True | iteration >= max_iterations | len(sources) >= max_sources`.
Иначе идёт на второй search-раунд.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool as make_tool
from pydantic import BaseModel, Field

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.deep_research.config import DeepResearchState
from giga_agent.modules.deep_research.prompts import REFLECT_SYSTEM
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)

logger = get_logger(__name__)


class _CoverageEntry(BaseModel):
    sub_question_id: int = Field(..., description="id подвопроса из плана")
    status: Literal["covered", "gap"] = Field(
        ..., description="covered — хватает данных; gap — нужно ещё искать"
    )
    new_queries: list[str] = Field(
        default_factory=list,
        description=(
            "Для gap: до 3 НОВЫХ поисковых запросов, отличных от уже выполненных. "
            "Для covered: пустой список."
        ),
    )


class _ReflectSchema(BaseModel):
    coverage: list[_CoverageEntry] = Field(
        ..., description="По одной записи на каждый подвопрос плана"
    )
    stop: bool = Field(
        ...,
        description=(
            "True если >=80% подвопросов covered или дальнейший поиск вряд ли "
            "добавит новое. False — нужна ещё итерация."
        ),
    )


@make_tool("submit_reflection", args_schema=_ReflectSchema)
def _submit_reflection(coverage, stop):  # type: ignore[override]
    """Submit reflection on research coverage."""
    _ = coverage, stop
    return "ok"


def _build_user_prompt(task: str, plan: list[dict], sources: list[dict]) -> str:
    plan_lines = []
    for sub in plan:
        if not isinstance(sub, dict):
            continue
        queries_str = " | ".join(sub.get("queries") or [])
        plan_lines.append(
            f"- id={sub.get('id')}: {sub.get('text', '')}\n  queries tried: {queries_str}"
        )
    plan_block = "\n".join(plan_lines) or "(план пуст)"

    src_lines = []
    for src in sources:
        summary = (src.get("summary") or "").strip()
        if not summary or summary.startswith("Нерелевантно"):
            continue
        ids = src.get("sub_question_ids") or []
        first_line = summary.splitlines()[0] if summary else ""
        src_lines.append(
            f"- source_id={src.get('id')} (sub_q_ids={ids}) — {first_line[:200]}"
        )
    src_block = "\n".join(src_lines) or "(релевантных источников пока нет)"

    return (
        f"Исходный запрос пользователя:\n{task}\n\n"
        f"План подвопросов:\n{plan_block}\n\n"
        f"Релевантные источники (только первые строки выжимок):\n{src_block}\n\n"
        "Оцени покрытие и вызови submit_reflection."
    )


async def reflect_node(state: DeepResearchState, config: RunnableConfig):
    task = (state.get("task") or "").strip()
    plan = state.get("plan") or []
    sources = state.get("sources") or []
    iteration = state.get("iteration", 0) + 1
    budget = state.get("budget") or {}
    max_iter = budget.get("max_iterations", 3)

    # Если это последняя разрешённая итерация — не зовём LLM, сразу стоп.
    if iteration >= max_iter or not plan:
        return {"iteration": iteration, "should_stop": True}

    factory = await get_session_factory()
    try:
        async with factory() as session:
            user = await get_current_user_from_config(config, session=session)
            llm = await resolve_user_llm(user, session=session, config=config)
    except Exception as exc:
        logger.warning(
            "deep_research.reflect: LLM resolution failed, stopping",
            error_type=type(exc).__name__,
        )
        return {"iteration": iteration, "should_stop": True}

    prompt = ChatPromptTemplate.from_messages(
        [("system", REFLECT_SYSTEM), MessagesPlaceholder("messages")]
    )
    chain = prompt | llm.with_config(tags=["nostream"]).bind_tools(
        [_submit_reflection],
        tool_choice="submit_reflection",
        parallel_tool_calls=False,
    )

    user_prompt = _build_user_prompt(task, plan, sources)
    try:
        resp = await chain.ainvoke({"messages": [("user", user_prompt)]})
    except Exception as exc:
        logger.warning(
            "deep_research.reflect: LLM call failed, stopping",
            error_type=type(exc).__name__,
        )
        return {"iteration": iteration, "should_stop": True}

    tool_calls = getattr(resp, "tool_calls", None) or []
    if not tool_calls:
        return {"iteration": iteration, "should_stop": True}

    args = tool_calls[0].get("args", {}) or {}
    coverage = args.get("coverage") or []
    stop_flag = bool(args.get("stop", False))

    # Индекс: sub_id → coverage entry
    cov_by_id: dict[int, dict] = {}
    for entry in coverage:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sub_question_id")
        if isinstance(sid, int):
            cov_by_id[sid] = entry

    updated_plan: list[dict] = []
    any_gap = False
    for sub in plan:
        if not isinstance(sub, dict):
            updated_plan.append(sub)
            continue
        updated = dict(sub)
        sid = updated.get("id")
        entry = cov_by_id.get(sid) if isinstance(sid, int) else None
        if entry:
            status = entry.get("status")
            if status in ("covered", "gap"):
                updated["status"] = status
            if status == "gap":
                any_gap = True
                new_qs = entry.get("new_queries") or []
                existing_qs = list(updated.get("queries") or [])
                existing_set = {q.strip() for q in existing_qs if isinstance(q, str)}
                for nq in new_qs:
                    if (
                        isinstance(nq, str)
                        and nq.strip()
                        and nq.strip() not in existing_set
                    ):
                        existing_qs.append(nq.strip())
                        existing_set.add(nq.strip())
                updated["queries"] = existing_qs
        updated_plan.append(updated)

    # Если LLM сказал stop=True, но есть gaps — уважаем stop (LLM мог решить,
    # что больше искать бессмысленно).
    should_stop = stop_flag or not any_gap
    return {
        "iteration": iteration,
        "plan": updated_plan,
        "should_stop": should_stop,
    }


def route_after_reflect(state: DeepResearchState):
    """search | compose."""
    budget = state.get("budget") or {}
    iteration = state.get("iteration", 0)
    sources = state.get("sources") or []

    if state.get("should_stop"):
        return "compose"
    if iteration >= budget.get("max_iterations", 1):
        return "compose"
    if len(sources) >= budget.get("max_sources", 40):
        return "compose"
    return "search"
