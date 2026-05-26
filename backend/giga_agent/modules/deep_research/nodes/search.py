"""Search node — один батчевый вызов поискового движка.

Собирает все queries всех подвопросов, отправляет одним запросом в
SearchEngineManager, парсит результаты и раскладывает по sub_question_ids.
Дедуп по нормализованному URL.
"""
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from giga_agent.core.db import get_session_factory
from giga_agent.modules.deep_research.config import (
    DEFAULT_SOURCES_PER_SUBQ,
    DeepResearchState,
)
from giga_agent.modules.deep_research.utils import is_blocked_domain, normalize_url
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_search_engine,
)


def _extract_results(raw_result: Any) -> list[dict[str, Any]]:
    """Tavily и совместимые движки возвращают разные формы. Нормализуем в список dict."""
    if raw_result is None:
        return []
    if isinstance(raw_result, list):
        return [item for item in raw_result if isinstance(item, dict)]
    if isinstance(raw_result, dict):
        for key in ("results", "items", "data"):
            value = raw_result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # Иногда сам result — это уже один item.
        if "url" in raw_result:
            return [raw_result]
    return []


def _item_fields(item: dict[str, Any]) -> tuple[str, str, str, float]:
    url = str(item.get("url") or item.get("link") or "").strip()
    title = str(item.get("title") or item.get("name") or "").strip()
    snippet = str(
        item.get("content")
        or item.get("snippet")
        or item.get("description")
        or ""
    ).strip()
    try:
        score = float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return url, title, snippet, score


async def search_node(state: DeepResearchState, config: RunnableConfig):
    plan = state.get("plan") or []
    budget = state.get("budget") or {}
    sources_cap = budget.get("sources_per_subq", DEFAULT_SOURCES_PER_SUBQ)
    max_sources = budget.get("max_sources", 40)
    existing_sources = state.get("sources") or []
    existing_count = len(existing_sources)
    already_searched = set(state.get("searched_queries") or [])

    # query_text → list[sub_question_id]. Пропускаем уже выполненные.
    query_to_subs: dict[str, list[int]] = {}
    ordered_queries: list[str] = []
    for sub in plan:
        if not isinstance(sub, dict):
            continue
        sub_id = sub.get("id")
        for q in sub.get("queries") or []:
            if not isinstance(q, str):
                continue
            key = q.strip()
            if not key or key in already_searched:
                continue
            if key not in query_to_subs:
                query_to_subs[key] = []
                ordered_queries.append(key)
            if sub_id is not None and sub_id not in query_to_subs[key]:
                query_to_subs[key].append(sub_id)

    if not ordered_queries:
        return {}

    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        engine = await resolve_user_search_engine(user, session=session, config=config)
    try:
        batch = await engine.search(ordered_queries)
    except Exception:
        return {}

    # per-subq капы и глобальная дедупликация по URL.
    seen_urls: set[str] = {
        normalize_url(s.get("url", "")) for s in existing_sources if s.get("url")
    }
    per_sub_count: dict[int, int] = {}
    for src in existing_sources:
        for sid in src.get("sub_question_ids", []) or []:
            per_sub_count[sid] = per_sub_count.get(sid, 0) + 1

    new_sources: list[dict] = []
    next_id = existing_count

    for entry in batch or []:
        if not isinstance(entry, dict):
            continue
        query_text = str(entry.get("query") or "").strip()
        sub_ids = query_to_subs.get(query_text, [])
        results = _extract_results(entry.get("result"))

        # сортируем по score DESC, чтобы брать лучшее первым.
        results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        for item in results:
            if existing_count + len(new_sources) >= max_sources:
                break
            url, title, snippet, score = _item_fields(item)
            if not url:
                continue
            if is_blocked_domain(url):
                # skip auth-walled / video-only / forbidden-домены до чтения
                continue
            norm = normalize_url(url)
            if not norm or norm in seen_urls:
                continue

            # проверяем per-sub капы — берём только если хоть один подвопрос ещё не исчерпан.
            relevant_subs = [
                sid for sid in sub_ids
                if per_sub_count.get(sid, 0) < sources_cap
            ] or sub_ids  # fallback — если все капы переполнены, всё равно берём
            if not relevant_subs:
                continue

            seen_urls.add(norm)
            for sid in relevant_subs:
                per_sub_count[sid] = per_sub_count.get(sid, 0) + 1

            new_sources.append(
                {
                    "id": next_id,
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                    "summary": "",
                    "sub_question_ids": relevant_subs,
                    "score": score,
                }
            )
            next_id += 1

        if existing_count + len(new_sources) >= max_sources:
            break

    # отметим подвопросы как searched.
    updated_plan = []
    for sub in plan:
        if not isinstance(sub, dict):
            updated_plan.append(sub)
            continue
        updated = dict(sub)
        if updated.get("status") == "pending":
            updated["status"] = "searched"
        updated_plan.append(updated)

    return {
        "sources": new_sources,
        "plan": updated_plan,
        "searched_queries": ordered_queries,
    }
