from __future__ import annotations

import asyncio
import importlib.metadata
import os
import uuid
from typing import Annotated
from urllib.parse import urlparse

import httpx
from langchain.tools import InjectedState, ToolRuntime
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool

from giga_agent.conf import get_settings
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.core.logging import get_logger
from giga_agent.utils.messages import filter_tool_calls

logger = get_logger(__name__)


PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Ты — опытный копирайтер-аналитик.
Тебе предоставлены выгрузки с сайта (тексты, таблицы, изображения).

**Твоя задача:**

1. Проанализировать весь полученный материал.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать итоговый ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * добавляет ссылки на релевантные изображения со страницы (с короткой подписью к каждой).

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * ссылки на изображения давай в формате `![alt-текст](ссылка)`, только если они реально помогают ответу
""",
        ),
        MessagesPlaceholder("messages"),
    ],
)


def _get_jina_base_url() -> str:
    return get_settings().giga_agent_scraper_jina_base_url


def _jina_reader_url(url: str) -> str:
    return _get_jina_base_url() + url.lstrip("/")


def _validate_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def _load_via_jina_reader(
    *,
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, str]:
    reader_url = _jina_reader_url(url)
    headers = {
        "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1",
    }
    jina_api_key = os.environ.get("JINA_API_KEY")
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
    response: httpx.Response | None = None
    try:
        response = await client.get(reader_url, headers=headers)
        response.raise_for_status()

        text = response.text.strip()
        if not text:
            raise ValueError("Jina Reader вернул пустой результат.")
        return {"url": url, "markdown": text}
    finally:
        if response is not None and response.is_closed is False:
            try:
                await response.aclose()
            except Exception:
                pass


async def _resolve_fast_llm(runtime: ToolRuntime):
    resolver = RuntimeResolver.from_config(runtime.config)
    fast_llm_runtime = await resolver.get_fast_llm_runtime()
    parallel_calls = await resolver.get_fast_llm_parallel_calls()
    llm = await fast_llm_runtime.get_llm()
    return (
        llm.bind(top_p=0.3).with_config(tags=["nostream"]),
        parallel_calls,
    )


async def _summarize_page(messages, response, llm, summarize_sem: asyncio.Semaphore):
    extract_ch = PROMPT | llm
    prepared_messages = list(messages or [])
    if prepared_messages:
        prepared_messages[-1] = filter_tool_calls(prepared_messages[-1])

    message = HumanMessage(
        content=f"""**Твоя задача:**

1. Проанализировать материал ниже.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать исходя из материала короткий ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * если в markdown есть ссылки на релевантные изображения (в том числе относительные), добавляет их в ответ с короткой подписью.

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * ссылки на изображения — в формате ![alt-текст](ссылка), только если относятся к ответу
  * относительные ссылки из markdown не удаляй и не переписывай

URL: {response["url"]}

Материал
----
{response["markdown"]}
----
Дай краткую информацию исходя из материала следуя своей инструкции по форматированию ответа""",
    )
    async with summarize_sem:
        resp = await extract_ch.ainvoke({"messages": prepared_messages + [message]})
    return {"url": response["url"], "result": resp.content}


def _format_fetch_error(url: str, exc: Exception) -> dict[str, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else "unknown"
        return {"url": url, "error": f"Ошибка загрузки страницы: HTTP {status}"}
    if isinstance(exc, httpx.TimeoutException):
        return {
            "url": url,
            "error": "Ошибка загрузки страницы: превышено время ожидания",
        }
    if isinstance(exc, httpx.HTTPError):
        return {"url": url, "error": f"Ошибка загрузки страницы: {str(exc)}"}
    return {"url": url, "error": str(exc)}


async def _process_url(
    *,
    url: str,
    messages,
    llm,
    client: httpx.AsyncClient,
    summarize_sem: asyncio.Semaphore,
) -> dict[str, str]:
    if not _validate_url(url):
        return {
            "url": url,
            "error": "Некорректный URL. Поддерживаются только http/https ссылки.",
        }
    try:
        page_data = await _load_via_jina_reader(
            client=client,
            url=url,
        )
        return await _summarize_page(messages, page_data, llm, summarize_sem)
    except Exception as exc:
        logger.exception(
            "Failed to fetch or summarize URL in scraper",
            url=url,
            error_type=type(exc).__name__,
        )
        return _format_fetch_error(url, exc)


@tool
async def get_urls(
    urls: list[str],
    runtime: ToolRuntime,
    state: Annotated[dict, InjectedState],
):
    """Скачивает список URLs и отдаёт краткую выжимку по каждой ссылке с учётом задачи пользователя.

    Реализация использует Jina Reader для извлечения текста/markdown со страниц.
    Если в ответе есть изображения, прикладывай их к ответу
    """
    llm, llm_parallel_calls = await _resolve_fast_llm(runtime)
    summarize_sem = asyncio.Semaphore(llm_parallel_calls)
    total_concurrency = get_settings().giga_agent_scraper_total_concurrency

    fetch_sem = asyncio.Semaphore(max(1, int(total_concurrency)))
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:

        async def _bounded(url: str):
            async with fetch_sem:
                return await _process_url(
                    url=url,
                    messages=state.get("messages", []),
                    llm=llm,
                    client=client,
                    summarize_sem=summarize_sem,
                )

        response = await asyncio.gather(*[_bounded(u) for u in urls])

    return {
        "results": response,
        "attention": "\nИспользуй результаты в своем ответе. Если в тексте есть релевантные изображения, добавь их ссылками в формате `![alt-текст](ссылка)`.",
    }
