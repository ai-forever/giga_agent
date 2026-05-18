"""Compose node — собирает markdown-черновик отчёта с цитатами [N].

В первый проход — generate from scratch на основе sources.
Если в state есть `critique` (после revise-петли от critique_node) — revise
черновик с учётом замечаний редактора.

Upload в sandbox вынесен в отдельный узел `finalize` (после accept от критика).
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.deep_research.config import DeepResearchState
from giga_agent.modules.deep_research.prompts import COMPOSE_SYSTEM
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)

logger = get_logger(__name__)


def _build_sources_block(sources: list[dict]) -> tuple[str, int]:
    """Markdown-блок с релевантными выжимками + число релевантных источников."""
    lines: list[str] = []
    relevant = 0
    for src in sources:
        summary = (src.get("summary") or "").strip()
        if not summary or summary.startswith("Нерелевантно"):
            continue
        relevant += 1
        sid = src.get("id", "?")
        title = (src.get("title") or "").strip() or "(без названия)"
        url = (src.get("url") or "").strip()
        citation_num = sid + 1 if isinstance(sid, int) else sid
        lines.append(
            f"[{citation_num}] {title}\nURL: {url}\nВыжимка:\n{summary}\n"
        )
    return "\n".join(lines), relevant


def _fallback_report(task: str, sources: list[dict]) -> str:
    return (
        f"# Исследование: {task}\n\n"
        "_Не удалось собрать отчёт — релевантных источников не найдено или "
        "LLM не ответил._\n\n## Источники\n"
        + "\n".join(
            f"[{(src.get('id') or 0) + 1}] {(src.get('title') or '—')}: {src.get('url', '')}"
            for src in sources
            if src.get("url")
        )
        + "\n"
    )


async def compose_node(state: DeepResearchState, config: RunnableConfig):
    task = (state.get("task") or "").strip()
    plan = state.get("plan") or []
    sources = state.get("sources") or []
    prev_draft = state.get("report_draft")
    critique = state.get("critique")
    is_revision = bool(prev_draft and critique)

    sources_block, relevant = _build_sources_block(sources)
    plan_lines = "\n".join(
        f"- ({sub.get('id')}) {sub.get('text', '')}"
        for sub in plan
        if isinstance(sub, dict)
    )

    if relevant == 0:
        return {
            "report_draft": _fallback_report(task, sources),
            # После fallback сразу финалим — не надо критиковать то, что мы и так
            # не смогли собрать.
            "critique_verdict": "accept",
            "critique": None,
        }

    try:
        factory = await get_session_factory()
        async with factory() as session:
            user = await get_current_user_from_config(config, session=session)
            llm = await resolve_user_llm(user, session=session, config=config)
        llm = llm.with_config(tags=["nostream"])
    except Exception as exc:
        logger.warning(
            "deep_research.compose: LLM resolution failed",
            error_type=type(exc).__name__,
        )
        return {
            "report_draft": _fallback_report(task, sources),
            "critique_verdict": "accept",
            "critique": None,
        }

    if is_revision:
        user_prompt = (
            f"Исходный запрос пользователя:\n{task}\n\n"
            f"План подвопросов:\n{plan_lines or '(пусто)'}\n\n"
            f"Источники:\n\n{sources_block}\n"
            f"=== Предыдущий черновик ===\n{prev_draft}\n\n"
            f"=== Критика редактора ===\n{critique}\n\n"
            "Перепиши отчёт, устранив замечания. Сохрани структуру и язык."
        )
    else:
        user_prompt = (
            f"Исходный запрос пользователя:\n{task}\n\n"
            f"План подвопросов:\n{plan_lines or '(пусто)'}\n\n"
            f"Источники (id — 1-based в цитатах [N]):\n\n{sources_block}\n"
            "Напиши финальный markdown-отчёт строго по структуре из системного промпта."
        )

    try:
        resp = await llm.ainvoke(
            [SystemMessage(COMPOSE_SYSTEM), HumanMessage(user_prompt)]
        )
        draft = (resp.content or "").strip() if hasattr(resp, "content") else str(resp)
        if not draft:
            draft = prev_draft or _fallback_report(task, sources)
    except Exception as exc:
        logger.warning(
            "deep_research.compose: LLM call failed",
            error_type=type(exc).__name__,
        )
        draft = prev_draft or _fallback_report(task, sources)

    # После генерации очищаем старую критику — critique_node снова её заполнит
    # (либо accept, либо свежий revise с новой критикой).
    return {"report_draft": draft, "critique": None, "critique_verdict": None}
