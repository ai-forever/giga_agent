from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from cashews import cache
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserShort
from giga_agent.utils.langgraph_sdk import get_client as get_langgraph_client

_JSON_PARSER = JsonOutputParser()
_MAX_TEXT_LEN = 1200
_MAX_THREADS_SCAN = 12

_STARTER_FALLBACK_POOL = [
    "Помоги сформулировать план на неделю по моему проекту",
    "Составь чеклист для запуска новой фичи",
    "Сравни два подхода и выбери лучший с аргументами",
    "Разбей задачу на шаги с приоритетами и сроками",
    "Напиши черновик письма клиенту в деловом тоне",
    "Придумай 5 гипотез для роста продукта",
    "Подготовь структуру презентации по итогам квартала",
    "Сделай план исследования темы с источниками",
    "Собери список рисков и как их снизить",
    "Сформулируй вопросы для интервью с пользователями",
]

_FOLLOWUP_FALLBACK_POOL = [
    "Сделай ответ короче и по пунктам",
    "Добавь практический пример",
    "Предложи альтернативный подход",
    "Какие основные риски и ограничения?",
    "С чего лучше начать в первую очередь?",
    "Сделай версию для новичка простыми словами",
]


@dataclass(frozen=True)
class SuggestionResult:
    suggestions: list[str]
    cached: bool
    based_on_pairs: int
    source_thread_count: int


def _langgraph_config(token: str) -> dict[str, Any]:
    return {"configurable": {"langgraph_auth_user": {"token": token}}}


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                value = part.get("text")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            elif isinstance(part, str) and part.strip():
                parts.append(part.strip())
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def _truncate(text: str, max_len: int = _MAX_TEXT_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def _sanitize_suggestions(value: Any, *, count: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split()).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(text[:280])
        if len(out) >= count:
            break
    return out


def _sample_pool(pool: list[str], *, count: int) -> list[str]:
    if count <= 0:
        return []
    if len(pool) <= count:
        return list(pool)
    return random.sample(pool, count)


def _extract_suggestions_from_json(raw: str, *, count: int) -> list[str]:
    try:
        payload = _JSON_PARSER.parse(raw)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    return _sanitize_suggestions(payload.get("suggestions"), count=count)


def _collect_pairs(
    messages: list[dict[str, Any]], *, max_pairs: int
) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    pending_human: str | None = None
    for msg in messages:
        msg_type = msg.get("type")
        content = _extract_text(msg.get("content"))
        if msg_type == "human":
            pending_human = _truncate(content) if content else None
            continue
        if msg_type != "ai" or pending_human is None:
            continue
        if not content:
            continue
        pair = {
            "human": pending_human,
            "ai": _truncate(content),
            "ai_id": str(msg.get("id") or ""),
        }
        pairs.append(pair)
        pending_human = None
    if len(pairs) <= max_pairs:
        return pairs
    return pairs[-max_pairs:]


def _extract_messages_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = state.get("values")
    if not isinstance(values, dict):
        return []
    messages = values.get("messages")
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


def _state_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _has_pending_approval_interrupt(state: dict[str, Any]) -> bool:
    interrupts = _state_get(state, "interrupts", []) or []
    for interrupt_item in interrupts:
        value = _state_get(interrupt_item, "value", {}) or {}
        if not isinstance(value, dict):
            continue
        if value.get("type") in {"approve", "tool_call"}:
            return True
    return False


def _cache_key_starter(user_id: str, *, count: int, limit_threads: int) -> str:
    return f"suggestions:starter:{user_id}:{count}:{limit_threads}"


def _cache_key_followup(
    thread_id: str, *, last_ai_id: str, count: int, pairs_limit: int
) -> str:
    return f"suggestions:followup:{thread_id}:{last_ai_id}:{count}:{pairs_limit}"


def _normalize_search_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        threads = raw.get("threads")
        if isinstance(threads, list):
            return [item for item in threads if isinstance(item, dict)]
    return []


async def _invoke_suggestions_llm(
    *,
    user: UserShort,
    db: AsyncSession,
    system_prompt: str,
    user_prompt: str,
    count: int,
) -> list[str]:
    llm_id = user.fast_llm_id or user.llm_id
    if llm_id is None:
        return []
    try:
        runtime = await LLMManager.resolve_by_id(llm_id, session=db)
        llm = await runtime.get_llm()
        response = await llm.with_config(tags=["nostream"]).ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        content = (
            str(response.content)
            if isinstance(response, AIMessage)
            else str(getattr(response, "content", response))
        )
    except Exception:
        return []
    return _extract_suggestions_from_json(content, count=count)


async def _collect_recent_thread_context(
    *,
    token: str,
    limit_threads: int,
) -> tuple[list[str], int]:
    client = get_langgraph_client(_langgraph_config(token))
    rows = await client.threads.search(
        limit=min(_MAX_THREADS_SCAN, max(limit_threads, 1) * 2),
        offset=0,
        sort_by="updated_at",
        sort_order="desc",
    )
    normalized_rows = _normalize_search_rows(rows)
    prompts: list[str] = []
    source_count = 0
    for row in normalized_rows:
        thread_id = str((row or {}).get("thread_id") or "").strip()
        if not thread_id or thread_id.startswith("temporary/"):
            continue
        try:
            state = await client.threads.get_state(thread_id)
        except Exception:
            continue
        pairs = _collect_pairs(_extract_messages_from_state(state), max_pairs=1)
        if not pairs:
            continue
        prompts.append(pairs[-1]["human"])
        source_count += 1
        if source_count >= limit_threads:
            break
    return prompts, source_count


async def get_starter_suggestions(
    *,
    token: str,
    user: UserShort,
    db: AsyncSession,
    count: int = 5,
    limit_threads: int = 5,
    refresh: bool = False,
) -> SuggestionResult:
    safe_count = max(1, min(count, 8))
    safe_limit_threads = max(1, min(limit_threads, 8))
    cache_key = _cache_key_starter(
        str(user.id), count=safe_count, limit_threads=safe_limit_threads
    )
    if not refresh:
        cached = await cache.get(cache_key)
        if isinstance(cached, dict):
            suggestions = _sanitize_suggestions(
                cached.get("suggestions"), count=safe_count
            )
            if suggestions:
                return SuggestionResult(
                    suggestions=suggestions,
                    cached=True,
                    based_on_pairs=0,
                    source_thread_count=int(cached.get("source_thread_count") or 0),
                )

    context_prompts, source_thread_count = await _collect_recent_thread_context(
        token=token,
        limit_threads=safe_limit_threads,
    )
    if not context_prompts:
        fallback = _sample_pool(_STARTER_FALLBACK_POOL, count=safe_count)
        return SuggestionResult(
            suggestions=fallback,
            cached=False,
            based_on_pairs=0,
            source_thread_count=0,
        )

    context_text = "\n".join(f"- {item}" for item in context_prompts)
    system_prompt = (
        "Ты помогаешь предложить стартовые запросы для нового чата.\n"
        'Верни только JSON: {"suggestions": ["...", "..."]}.\n'
        "Требования:\n"
        "- suggestions: массив из коротких полезных пользовательских запросов\n"
        "- без нумерации, без пояснений, без markdown\n"
        "- каждый запрос самостоятельный и конкретный\n"
    )
    user_prompt = (
        f"На основе недавних запросов пользователя из разных чатов сгенерируй {safe_count} новых рекомендаций.\n"
        f"Недавние запросы:\n{context_text}"
    )
    generated = await _invoke_suggestions_llm(
        user=user,
        db=db,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        count=safe_count,
    )
    suggestions = generated or _sample_pool(_STARTER_FALLBACK_POOL, count=safe_count)
    await cache.set(
        cache_key,
        {"suggestions": suggestions, "source_thread_count": source_thread_count},
        expire="10m",
    )
    return SuggestionResult(
        suggestions=suggestions,
        cached=False,
        based_on_pairs=0,
        source_thread_count=source_thread_count,
    )


async def get_follow_up_suggestions(
    *,
    token: str,
    thread_id: str,
    user: UserShort,
    db: AsyncSession,
    count: int = 3,
    pairs_limit: int = 5,
    refresh: bool = False,
) -> SuggestionResult:
    safe_count = max(1, min(count, 5))
    safe_pairs_limit = max(1, min(pairs_limit, 5))
    client = get_langgraph_client(_langgraph_config(token))
    state = await client.threads.get_state(thread_id)
    if _has_pending_approval_interrupt(state):
        return SuggestionResult(
            suggestions=[],
            cached=False,
            based_on_pairs=0,
            source_thread_count=0,
        )
    pairs = _collect_pairs(
        _extract_messages_from_state(state),
        max_pairs=safe_pairs_limit,
    )
    if not pairs:
        return SuggestionResult(
            suggestions=_sample_pool(_FOLLOWUP_FALLBACK_POOL, count=safe_count),
            cached=False,
            based_on_pairs=0,
            source_thread_count=0,
        )

    last_ai_id = pairs[-1].get("ai_id") or "none"
    cache_key = _cache_key_followup(
        thread_id,
        last_ai_id=last_ai_id,
        count=safe_count,
        pairs_limit=safe_pairs_limit,
    )
    if not refresh:
        cached = await cache.get(cache_key)
        if isinstance(cached, dict):
            suggestions = _sanitize_suggestions(
                cached.get("suggestions"), count=safe_count
            )
            if suggestions:
                return SuggestionResult(
                    suggestions=suggestions,
                    cached=True,
                    based_on_pairs=len(pairs),
                    source_thread_count=0,
                )

    context_lines = []
    for idx, pair in enumerate(pairs, start=1):
        context_lines.append(f"Пара {idx}. Вопрос: {pair['human']}")
        context_lines.append(f"Пара {idx}. Ответ: {pair['ai']}")
    context_text = "\n".join(context_lines)

    system_prompt = (
        "Ты предлагаешь короткие follow-up запросы после ответа ассистента.\n"
        'Верни только JSON: {"suggestions": ["...", "..."]}.\n'
        "Требования:\n"
        "- suggestions: массив релевантных следующих вопросов\n"
        "- без нумерации, без пояснений, без markdown\n"
        "- каждый пункт <= 120 символов\n"
    )
    user_prompt = (
        f"Сгенерируй {safe_count} follow-up запроса для продолжения текущего диалога.\n"
        "Запросы должны быть сформированы от лица пользователя и предполагать его дальнейшие намерения"
        f"Контекст последних пар:\n{context_text}"
    )
    generated = await _invoke_suggestions_llm(
        user=user,
        db=db,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        count=safe_count,
    )
    suggestions = generated or _sample_pool(_FOLLOWUP_FALLBACK_POOL, count=safe_count)
    await cache.set(
        cache_key,
        {"suggestions": suggestions},
        expire="10m",
    )
    return SuggestionResult(
        suggestions=suggestions,
        cached=False,
        based_on_pairs=len(pairs),
        source_thread_count=0,
    )
