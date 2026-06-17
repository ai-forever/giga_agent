"""Critique node — редактор проверяет черновик отчёта.

LLM со structured output (bind_tools) выдаёт:
- verdict: "accept" | "revise"
- critique_text: список конкретных замечаний (для revise) или «ok» (для accept).

Роутер `route_after_critique`:
- accept → finalize (upload + end)
- revise + осталось revisions → compose (revision mode)
- revise + лимит revisions исчерпан → finalize (принимаем как есть)
- no draft → finalize (fallback ветка)
"""
from __future__ import annotations

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool as make_tool
from pydantic import BaseModel, Field

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.deep_research.config import (
    DEFAULT_MAX_REVISIONS,
    DeepResearchState,
)
from giga_agent.modules.deep_research.prompts import CRITIQUE_SYSTEM
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)

logger = get_logger(__name__)


class _CritiqueSchema(BaseModel):
    verdict: Literal["accept", "revise"] = Field(
        ...,
        description="accept — отчёт ок; revise — требуются исправления.",
    )
    critique_text: str = Field(
        ...,
        description=(
            "Для revise — подробный список замечаний с указанием конкретных "
            "мест в тексте. Для accept — коротко, напр. «замечаний нет»."
        ),
    )


@make_tool("submit_critique", args_schema=_CritiqueSchema)
def _submit_critique(verdict, critique_text):  # type: ignore[override]
    """Submit critique verdict on the report draft."""
    _ = verdict, critique_text
    return "ok"


def _build_sources_summary(sources: list[dict]) -> str:
    lines = []
    for src in sources:
        summary = (src.get("summary") or "").strip()
        if not summary or summary.startswith("Нерелевантно"):
            continue
        sid = src.get("id", "?")
        citation_num = sid + 1 if isinstance(sid, int) else sid
        title = (src.get("title") or "").strip() or "(без названия)"
        url = (src.get("url") or "").strip()
        first_line = summary.splitlines()[0] if summary else ""
        lines.append(f"[{citation_num}] {title} — {url}\n  {first_line[:200]}")
    return "\n".join(lines) or "(релевантных источников нет)"


async def critique_node(state: DeepResearchState, config: RunnableConfig):
    draft = state.get("report_draft") or ""
    if not draft.strip():
        return {"critique_verdict": "accept", "critique": None}

    task = (state.get("task") or "").strip()
    plan = state.get("plan") or []
    sources = state.get("sources") or []

    try:
        factory = await get_session_factory()
        async with factory() as session:
            user = await get_current_user_from_config(config, session=session)
            llm = await resolve_user_llm(user, session=session, config=config)
    except Exception as exc:
        logger.warning(
            "deep_research.critique: LLM resolution failed, accepting as-is",
            error_type=type(exc).__name__,
        )
        return {"critique_verdict": "accept", "critique": None}

    prompt = ChatPromptTemplate.from_messages(
        [("system", CRITIQUE_SYSTEM), MessagesPlaceholder("messages")]
    )
    chain = prompt | llm.with_config(tags=["nostream"]).bind_tools(
        [_submit_critique],
        tool_choice="submit_critique",
        parallel_tool_calls=False,
    )

    plan_lines = "\n".join(
        f"- ({sub.get('id')}) {sub.get('text', '')}"
        for sub in plan
        if isinstance(sub, dict)
    )
    user_prompt = (
        f"Исходный запрос пользователя:\n{task}\n\n"
        f"План подвопросов:\n{plan_lines or '(пусто)'}\n\n"
        f"Источники (первые строки выжимок):\n{_build_sources_summary(sources)}\n\n"
        f"=== Черновик отчёта ===\n{draft}\n\n"
        "Оцени черновик и вызови submit_critique."
    )

    try:
        resp = await chain.ainvoke({"messages": [("user", user_prompt)]})
    except Exception as exc:
        logger.warning(
            "deep_research.critique: LLM call failed, accepting as-is",
            error_type=type(exc).__name__,
        )
        return {"critique_verdict": "accept", "critique": None}

    tool_calls = getattr(resp, "tool_calls", None) or []
    if not tool_calls:
        return {"critique_verdict": "accept", "critique": None}

    args = tool_calls[0].get("args", {}) or {}
    verdict_raw = args.get("verdict")
    verdict: Literal["accept", "revise"] = (
        "revise" if verdict_raw == "revise" else "accept"
    )
    critique_text = (args.get("critique_text") or "").strip() or None

    if verdict == "accept":
        return {"critique_verdict": "accept", "critique": None}

    new_count = (state.get("revision_count") or 0) + 1
    return {
        "critique_verdict": "revise",
        "critique": critique_text,
        "revision_count": new_count,
    }


def route_after_critique(state: DeepResearchState):
    """compose (revise) | finalize."""
    verdict = state.get("critique_verdict")
    budget = state.get("budget") or {}
    max_revisions = budget.get("max_revisions", DEFAULT_MAX_REVISIONS)
    revision_count = state.get("revision_count") or 0

    if verdict == "revise" and revision_count <= max_revisions:
        return "compose"
    # accept / лимит ревизий / нет verdict → finalize
    return "finalize"
