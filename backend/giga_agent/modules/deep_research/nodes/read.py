"""Read node — параллельное чтение найденных URL через Jina Reader + LLM-суммаризация.

Переиспользует приватные хелперы `modules.scraper.tool._load_via_jina_reader`,
`_validate_url`, `_format_fetch_error` (см. решение #12 в ARCHITECTURE.md).
Свой LLM-резолвер и свой промпт суммаризации — сфокусирован на подвопросах,
а не на общем ответе пользователю.
"""

from __future__ import annotations

import asyncio

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.modules.deep_research.config import (
    DEFAULT_MAX_READ_PER_ITERATION,
    DeepResearchState,
)
from giga_agent.modules.scraper.tool import (
    _format_fetch_error,
    _load_via_jina_reader,
    _validate_url,
)
from giga_agent.modules.subagents_legacy.runtime import _get_or_create_resolver

logger = get_logger(__name__)


# Жёсткий локальный лимит concurrency для Jina Reader: free-tier даёт 429 при
# >3 параллельных запросов. Берём min() с пользовательским scraper-settings, но
# не позволяем выше 3.
DEEP_RESEARCH_FETCH_CONCURRENCY_CAP = 3
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BASE_DELAY_S = 1.2
FETCH_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


async def _fetch_with_retry(*, client: httpx.AsyncClient, url: str) -> dict[str, str]:
    """Jina Reader с retry на transient-ошибках (rate-limit, 5xx).

    403 не ретраим — это forbidden сайт. Экспоненциальная задержка с джиттером.
    """
    last_exc: Exception | None = None
    for attempt in range(FETCH_RETRY_ATTEMPTS):
        try:
            return await _load_via_jina_reader(client=client, url=url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            last_exc = exc
            if status not in FETCH_RETRYABLE_STATUS:
                raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
        if attempt + 1 < FETCH_RETRY_ATTEMPTS:
            delay = FETCH_RETRY_BASE_DELAY_S * (2**attempt)
            # джиттер 0.5x..1.5x, чтобы размазать волну
            import random

            await asyncio.sleep(delay * (0.5 + random.random()))
    assert last_exc is not None
    raise last_exc


SUMMARIZE_SYSTEM = """Ты — исследовательский ассистент. Тебе дана исходная задача пользователя,
подвопросы плана и содержимое одной веб-страницы.

Выдай короткое (≤250 слов) саммари страницы, которое:
- Содержит ТОЛЬКО факты, цифры, цитаты и примеры, релевантные к задаче/подвопросам.
- Не пересказывает всю страницу — только фрагменты, которые можно будет процитировать в итоговом отчёте.
- Если страница не по теме или пустая — напиши одной строкой «Нерелевантно: <причина>».
- Сохраняй оригинальные числа, имена, термины без перевода.

Выдай markdown без заголовков — просто плотный содержательный текст."""


async def _resolve_fast_llm_from_config(config: RunnableConfig):
    resolver = await _get_or_create_resolver(config)
    llm_runtime = await resolver.get_fast_llm_runtime()
    parallel_calls = await resolver.get_fast_llm_parallel_calls()
    llm = await llm_runtime.get_llm()
    return llm.bind(top_p=0.3).with_config(tags=["nostream"]), parallel_calls


def _build_summarize_user_prompt(
    *, task: str, plan: list[dict], url: str, markdown: str
) -> str:
    plan_lines = "\n".join(
        f"- {sub.get('text', '')}" for sub in plan if isinstance(sub, dict)
    )
    return (
        f"Исходная задача пользователя:\n{task}\n\n"
        f"Подвопросы плана:\n{plan_lines or '(план не сгенерирован)'}\n\n"
        f"URL: {url}\n\n"
        f"Содержимое страницы:\n----\n{markdown}\n----\n"
    )


async def _process_one(
    *,
    source: dict,
    task: str,
    plan: list[dict],
    llm,
    client: httpx.AsyncClient,
    fetch_sem: asyncio.Semaphore,
    summarize_sem: asyncio.Semaphore,
) -> dict:
    url = source.get("url", "")
    source_id = source.get("id")
    if not _validate_url(url):
        return {
            "id": source_id,
            "url": url,
            "summary": "Нерелевантно: некорректный URL",
        }
    try:
        async with fetch_sem:
            page = await _fetch_with_retry(client=client, url=url)
    except Exception as exc:
        logger.warning(
            "deep_research.read: Jina Reader failed",
            url=url,
            error_type=type(exc).__name__,
        )
        err = _format_fetch_error(url, exc)
        return {
            "id": source_id,
            "url": url,
            "summary": f"Нерелевантно: {err.get('error', 'ошибка загрузки')}",
        }

    user_prompt = _build_summarize_user_prompt(
        task=task, plan=plan, url=url, markdown=page.get("markdown", "")
    )
    messages = [SystemMessage(SUMMARIZE_SYSTEM), HumanMessage(user_prompt)]
    try:
        async with summarize_sem:
            resp = await llm.ainvoke(messages)
    except Exception as exc:
        logger.warning(
            "deep_research.read: summarization failed",
            url=url,
            error_type=type(exc).__name__,
        )
        return {
            "id": source_id,
            "url": url,
            "summary": "Нерелевантно: ошибка суммаризации",
        }

    summary = (
        (resp.content or "").strip() if hasattr(resp, "content") else str(resp).strip()
    )
    return {"id": source_id, "url": url, "summary": summary}


async def read_node(state: DeepResearchState, config: RunnableConfig):
    task = state.get("task", "")
    plan = state.get("plan") or []
    sources = state.get("sources") or []
    budget = state.get("budget") or {}
    max_read = budget.get("max_read_per_iteration", DEFAULT_MAX_READ_PER_ITERATION)

    # Берём только те, что ещё не прочитаны (summary пустой).
    targets = [s for s in sources if not (s.get("summary") or "").strip()][:max_read]
    if not targets:
        return {}

    try:
        llm, llm_parallel = await _resolve_fast_llm_from_config(config)
    except Exception as exc:
        logger.warning(
            "deep_research.read: fast LLM resolution failed",
            error_type=type(exc).__name__,
        )
        return {}

    settings = get_settings()
    fetch_concurrency = min(
        DEEP_RESEARCH_FETCH_CONCURRENCY_CAP,
        max(1, int(settings.giga_agent_scraper_total_concurrency)),
    )
    fetch_sem = asyncio.Semaphore(fetch_concurrency)
    summarize_sem = asyncio.Semaphore(llm_parallel)

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        updates = await asyncio.gather(
            *[
                _process_one(
                    source=src,
                    task=task,
                    plan=plan,
                    llm=llm,
                    client=client,
                    fetch_sem=fetch_sem,
                    summarize_sem=summarize_sem,
                )
                for src in targets
            ],
            return_exceptions=False,
        )

    # Отмечаем подвопросы, для которых есть хоть один прочитанный источник, как read.
    read_sub_ids: set[int] = set()
    for src in targets:
        for sid in src.get("sub_question_ids") or []:
            read_sub_ids.add(sid)

    updated_plan = []
    for sub in plan:
        if not isinstance(sub, dict):
            updated_plan.append(sub)
            continue
        updated = dict(sub)
        if updated.get("id") in read_sub_ids and updated.get("status") in (
            "pending",
            "searched",
        ):
            updated["status"] = "read"
        updated_plan.append(updated)

    return {"sources": updates, "plan": updated_plan}
