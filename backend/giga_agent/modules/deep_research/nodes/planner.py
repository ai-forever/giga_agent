"""Planner node — декомпозирует запрос на подвопросы с diverse queries.

Возвращает 2–6 подвопросов, для каждого — 3–4 разных поисковых запроса
(разные языки, разные формулировки).

LLM вызывается через `bind_tools(submit_plan)` с `parallel_tool_calls=False`,
как в существующих субагентах (landing_agent/graph.py).
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    tool_extras,
)
from giga_agent.core.db import get_session_factory
from giga_agent.modules.deep_research.config import (
    DEFAULT_MAX_SUBQUESTIONS,
    DEFAULT_QUERIES_PER_SUBQ,
    DeepResearchState,
    default_budget,
)
from giga_agent.modules.deep_research.prompts import PLANNER_SYSTEM
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)


class _SubQuestionSchema(BaseModel):
    text: str = Field(
        ...,
        description="Текст подвопроса на языке исходного запроса пользователя",
    )
    queries: list[str] = Field(
        ...,
        description=(
            "3–4 разных поисковых запроса. Обязательно включи варианты на "
            "английском для интернациональных тем. Разные формулировки, "
            "разные ключевые слова."
        ),
    )


class _PlanSchema(BaseModel):
    sub_questions: list[_SubQuestionSchema] = Field(
        ...,
        description=f"2–{DEFAULT_MAX_SUBQUESTIONS} независимых подвопросов",
    )


@tool(
    "submit_plan",
    args_schema=_PlanSchema,
    extras=tool_extras(ToolEffect.WRITE, plan_mode=ToolPlanMode.ALLOW),
)
def submit_plan(sub_questions: list[_SubQuestionSchema]) -> str:
    """Submit the research plan — list of sub-questions with diverse search queries each."""
    _ = sub_questions
    return "ok"


def _fallback_plan(task: str) -> list[dict]:
    return [
        {
            "id": 0,
            "text": task,
            "status": "pending",
            "queries": [task] if task else [],
        }
    ]


async def planner_node(state: DeepResearchState, config: RunnableConfig):
    task = (state.get("task") or "").strip()
    budget = state.get("budget") or default_budget()
    queries_cap = budget.get("queries_per_subq", DEFAULT_QUERIES_PER_SUBQ)
    subq_cap = budget.get("max_subquestions", DEFAULT_MAX_SUBQUESTIONS)

    if not task:
        return {"plan": [], "iteration": 0, "budget": budget}

    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        llm = await resolve_user_llm(user, session=session, config=config)

    prompt = ChatPromptTemplate.from_messages(
        [("system", PLANNER_SYSTEM), MessagesPlaceholder("messages")]
    )
    chain = prompt | llm.with_config(tags=["nostream"]).bind_tools(
        [submit_plan],
        tool_choice="submit_plan",
        parallel_tool_calls=False,
    )

    try:
        resp = await chain.ainvoke(
            {"messages": [("user", f"Запрос пользователя:\n{task}")]}
        )
    except Exception:
        return {
            "plan": _fallback_plan(task),
            "iteration": 0,
            "budget": budget,
        }

    tool_calls = getattr(resp, "tool_calls", None) or []
    if not tool_calls:
        return {
            "plan": _fallback_plan(task),
            "iteration": 0,
            "budget": budget,
        }

    args = tool_calls[0].get("args", {}) or {}
    raw_subs = args.get("sub_questions") or []

    plan: list[dict] = []
    for idx, item in enumerate(raw_subs[:subq_cap]):
        text = (item.get("text") if isinstance(item, dict) else "") or ""
        queries = item.get("queries") if isinstance(item, dict) else None
        if not isinstance(queries, list):
            queries = []
        # Дедуп + трим + cap.
        seen: set[str] = set()
        clean_queries: list[str] = []
        for q in queries:
            if not isinstance(q, str):
                continue
            q_clean = q.strip()
            if not q_clean or q_clean in seen:
                continue
            seen.add(q_clean)
            clean_queries.append(q_clean)
            if len(clean_queries) >= queries_cap:
                break
        if not clean_queries:
            clean_queries = [text or task]
        plan.append(
            {
                "id": idx,
                "text": text.strip() or task,
                "status": "pending",
                "queries": clean_queries,
            }
        )

    if not plan:
        plan = _fallback_plan(task)

    return {"plan": plan, "iteration": 0, "budget": budget}
