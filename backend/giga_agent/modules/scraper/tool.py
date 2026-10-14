from __future__ import annotations

import asyncio
import os
import uuid
from typing import Annotated
from urllib.parse import urlparse

import httpx
from langchain.tools import InjectedState, ToolRuntime
from langchain_core.tools import tool
from langchain_tavily import TavilyExtract

from giga_agent.conf import get_settings
from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.logging import get_logger
from giga_agent.modules.subagents_legacy.uploads import (
    LegacyUploadFileSpec,
    resolve_upload_prefix,
    upload_files_for_runtime_user,
)

logger = get_logger(__name__)


MAX_URLS_PER_CALL = 4
TOTAL_CONTENT_THRESHOLD_CHARS = 20_000
PER_RESULT_PREVIEW_CHARS = 5_000


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


def _get_tavily_api_key() -> str:
    return (os.getenv("TAVILY_API_KEY") or "").strip()


def _get_tavily_extractor() -> TavilyExtract:
    api_key = _get_tavily_api_key()
    if not api_key:
        raise ValueError("TAVILY_API_KEY is required when GIGA_AGENT_SCRAPER=tavily.")
    return TavilyExtract(
        tavily_api_key=api_key,
        extract_depth="advanced",
        include_images=True,
        format="markdown",
    )


def _is_tavily_mode() -> bool:
    return get_settings().giga_agent_scraper == "tavily"


async def _load_via_tavily_extract(
    *,
    extractor: TavilyExtract,
    url: str,
) -> dict[str, object]:
    raw_response = await extractor.ainvoke({"urls": [url]})
    if not isinstance(raw_response, dict):
        raise ValueError("Tavily Extract вернул ответ неизвестного формата.")

    if raw_response.get("error") is not None:
        raise ValueError(str(raw_response["error"]))

    results = raw_response.get("results") or []
    if not isinstance(results, list) or not results:
        failed_results = raw_response.get("failed_results") or []
        failure = (
            failed_results[0]
            if isinstance(failed_results, list) and failed_results
            else None
        )
        if isinstance(failure, dict) and failure.get("error"):
            raise ValueError(str(failure["error"]))
        raise ValueError("Tavily Extract не вернул содержимое страницы.")

    result = results[0]
    if not isinstance(result, dict):
        raise ValueError("Tavily Extract вернул результат неизвестного формата.")

    markdown = result.get("raw_content") or result.get("content") or ""
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("Tavily Extract вернул пустое содержимое страницы.")

    response: dict[str, object] = {
        "url": str(result.get("url") or url),
        "markdown": markdown,
    }
    for field in ("images", "favicon"):
        value = result.get(field) or raw_response.get(field)
        if value:
            response[field] = value
    return response


async def _load_via_scraper(
    *,
    client: httpx.AsyncClient,
    url: str,
    tavily_extractor: TavilyExtract | None = None,
) -> dict[str, object]:
    if _is_tavily_mode():
        extractor = tavily_extractor or _get_tavily_extractor()
        return await _load_via_tavily_extract(extractor=extractor, url=url)
    return await _load_via_jina_reader(client=client, url=url)


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
    client: httpx.AsyncClient,
    tavily_extractor: TavilyExtract | None = None,
) -> dict[str, object]:
    if not _validate_url(url):
        return {
            "url": url,
            "error": "Некорректный URL. Поддерживаются только http/https ссылки.",
        }
    try:
        page_data = await _load_via_scraper(
            client=client,
            url=url,
            tavily_extractor=tavily_extractor,
        )
        return page_data
    except Exception as exc:
        logger.exception(
            "Failed to fetch URL in scraper",
            url=url,
            error_type=type(exc).__name__,
        )
        return _format_fetch_error(url, exc)


@tool(
    extras=tool_extras(
        ToolEffect.READ,
        repl_skip=True,
        not_compress=True,
        not_process=True,
    )
)
async def get_urls(
    urls: list[str],
    runtime: ToolRuntime,
    state: Annotated[dict, InjectedState],
):
    """Получает markdown-содержимое списка URLs и содержимое по каждой ссылке с учётом задачи пользователя.
    Если в ответе есть изображения, прикладывай их к ответу.
    За один вызов можно передать не более 4 ссылок — лишние будут проигнорированы.
    Если суммарный объём контента слишком большой, в ответе вернётся только превью каждой страницы,
    а полный markdown будет сохранён в sandbox — продолжать чтение можно через read_file(sandbox_path=...).
    """
    notices: list[str] = []
    if len(urls) > MAX_URLS_PER_CALL:
        notices.append(
            f"Передано {len(urls)} ссылок, обработаны только первые {MAX_URLS_PER_CALL}."
        )
        urls = urls[:MAX_URLS_PER_CALL]

    total_concurrency = get_settings().giga_agent_scraper_total_concurrency
    tavily_extractor = _get_tavily_extractor() if _is_tavily_mode() else None

    fetch_sem = asyncio.Semaphore(max(1, int(total_concurrency)))
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:

        async def _bounded(url: str):
            async with fetch_sem:
                return await _process_url(
                    url=url,
                    client=client,
                    tavily_extractor=tavily_extractor,
                )

        response = await asyncio.gather(*[_bounded(u) for u in urls])

    total_chars = sum(len(item.get("markdown") or "") for item in response)
    if total_chars > TOTAL_CONTENT_THRESHOLD_CHARS:
        prefix = resolve_upload_prefix(runtime)
        files_to_upload: list[LegacyUploadFileSpec] = []
        upload_idx_to_response_idx: list[int] = []
        for idx, item in enumerate(response):
            markdown = item.get("markdown")
            if not markdown or len(markdown) <= PER_RESULT_PREVIEW_CHARS:
                continue
            files_to_upload.append(
                {
                    "file_name": f"{prefix}/scraper-{uuid.uuid4().hex}.md",
                    "file_type": "text",
                    "content": markdown.encode("utf-8"),
                }
            )
            upload_idx_to_response_idx.append(idx)

        if files_to_upload:
            try:
                uploaded = await upload_files_for_runtime_user(
                    runtime, files=files_to_upload
                )
            except Exception as exc:
                logger.exception(
                    "Failed to persist scraper markdown overflow",
                    error_type=type(exc).__name__,
                )
                uploaded = []

            for upload_pos, file in enumerate(uploaded):
                if upload_pos >= len(upload_idx_to_response_idx):
                    break
                response_idx = upload_idx_to_response_idx[upload_pos]
                full_markdown = response[response_idx]["markdown"]
                response[response_idx]["markdown"] = (
                    full_markdown[:PER_RESULT_PREVIEW_CHARS]
                    + "\n…[обрезано, продолжение в full_markdown_path]"
                )
                response[response_idx]["full_markdown_path"] = file.sandbox_path
                response[response_idx]["total_markdown_chars"] = len(full_markdown)
                response[response_idx]["truncated"] = True

        notices.append(
            f"Суммарный объём контента превысил {TOTAL_CONTENT_THRESHOLD_CHARS} символов: "
            f"для длинных результатов показаны первые {PER_RESULT_PREVIEW_CHARS} символов, "
            "полный markdown сохранён в sandbox — путь доступен в поле `full_markdown_path`. "
            "Продолжай чтение через read_file(sandbox_path=<full_markdown_path>)."
        )

    payload: dict = {
        "results": response,
        "attention": "\nИспользуй результаты в своем ответе. Если в тексте есть релевантные изображения, добавь их ссылками в формате `![alt-текст](ссылка)`.",
    }
    if notices:
        payload["notices"] = notices
    return payload
