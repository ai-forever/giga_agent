import asyncio
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx

from giga_agent.modules.scraper import tool as scraper_tool
from giga_agent.modules.scraper.tool import get_urls


class _FakeResponse:
    def __init__(self, *, url: str, status_code: int = 200, text: str = "", content_type: str = "text/html"):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        value = self._responses[url]
        if isinstance(value, Exception):
            raise value
        return value


class _FakeLLMChain:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return types.SimpleNamespace(content="summary")


class _FakeLLM:
    def bind(self, **kwargs):
        _ = kwargs
        return self

    def with_config(self, **kwargs):
        _ = kwargs
        return _FakeLLMChain()


class ScraperToolTests(unittest.IsolatedAsyncioTestCase):
    def _runtime(self):
        owner_id = uuid.uuid4()
        return types.SimpleNamespace(
            config={"configurable": {"langgraph_auth_user": {"identity": str(owner_id)}}}
        )

    async def test_get_urls_success_html_returns_result_without_error(self):
        runtime = self._runtime()
        state = {"messages": []}
        extracted = "# Title\n\nBody"
        client = _FakeClient(
            {
                "https://r.jina.ai/https://example.com": _FakeResponse(
                    url="https://r.jina.ai/https://example.com",
                    text=extracted,
                    content_type="text/plain",
                )
            }
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        user = types.SimpleNamespace(
            id=uuid.uuid4(),
            llm_id=uuid.uuid4(),
            fast_llm_id=uuid.uuid4(),
        )
        llm_runtime = types.SimpleNamespace(llm=_FakeLLM())

        with patch(
            "giga_agent.modules.scraper.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.scraper.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=types.SimpleNamespace(parallel_calls=2)),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ), patch(
            "giga_agent.modules.scraper.tool.httpx.AsyncClient",
            return_value=client,
        ), patch(
            "giga_agent.modules.scraper.tool._summarize_page",
            AsyncMock(return_value={"url": "https://example.com", "result": "summary"}),
        ):
            assert get_urls.coroutine is not None
            result = await get_urls.coroutine(
                urls=["https://example.com"],
                runtime=runtime,
                state=state,
            )

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.com")
        self.assertIn("result", result["results"][0])
        self.assertNotIn("error", result["results"][0])

    async def test_html_is_converted_to_markdown_with_image_links(self):
        extracted = "Текст\n\n![](/img/a.png)\n\n![](https://cdn.example.com/b.jpg)"
        fake_client = _FakeClient(
            {
                "https://r.jina.ai/https://example.com/path": _FakeResponse(
                    url="https://r.jina.ai/https://example.com/path",
                    text=extracted,
                    content_type="text/plain",
                )
            }
        )
        response = await scraper_tool._load_page(client=fake_client, url="https://example.com/path")
        self.assertIn("![](/img/a.png)", response["markdown"])
        self.assertIn("![](https://cdn.example.com/b.jpg)", response["markdown"])

    async def test_invalid_url_returns_soft_error(self):
        result = await scraper_tool._process_url(
            url="ftp://example.com",
            messages=[],
            llm=object(),
            client=_FakeClient({}),
            summarize_sem=asyncio.Semaphore(1),
        )
        self.assertEqual(result["url"], "ftp://example.com")
        self.assertIn("error", result)

    async def test_timeout_returns_soft_error(self):
        result = await scraper_tool._process_url(
            url="https://timeout.example.com",
            messages=[],
            llm=object(),
            client=_FakeClient(
                {"https://r.jina.ai/https://timeout.example.com": httpx.TimeoutException("timeout")}
            ),
            summarize_sem=asyncio.Semaphore(1),
        )
        self.assertEqual(result["url"], "https://timeout.example.com")
        self.assertIn("error", result)
        self.assertIn("время ожидания", result["error"])

    async def test_http_status_error_returns_soft_error(self):
        request = httpx.Request("GET", "https://r.jina.ai/https://example.com/404")
        response = httpx.Response(404, request=request)
        result = await scraper_tool._process_url(
            url="https://example.com/404",
            messages=[],
            llm=object(),
            client=_FakeClient(
                {
                    "https://r.jina.ai/https://example.com/404": httpx.HTTPStatusError(
                        "404",
                        request=request,
                        response=response,
                    )
                }
            ),
            summarize_sem=asyncio.Semaphore(1),
        )
        self.assertEqual(result["url"], "https://example.com/404")
        self.assertEqual(result["error"], "Ошибка загрузки страницы: HTTP 404")

    async def test_mixed_batch_partial_success(self):
        runtime = self._runtime()
        state = {"messages": []}
        extracted = "ok"
        client = _FakeClient(
            {
                "https://r.jina.ai/https://ok.example.com": _FakeResponse(
                    url="https://r.jina.ai/https://ok.example.com",
                    text=extracted,
                    content_type="text/plain",
                ),
            }
        )

        @asynccontextmanager
        async def _session_context():
            yield object()

        user = types.SimpleNamespace(
            id=uuid.uuid4(),
            llm_id=uuid.uuid4(),
            fast_llm_id=None,
        )
        llm_runtime = types.SimpleNamespace(llm=_FakeLLM())

        with patch(
            "giga_agent.modules.scraper.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.scraper.tool.UserRepository.get_cached_or_db",
            AsyncMock(return_value=user),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=types.SimpleNamespace(parallel_calls=2)),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ), patch(
            "giga_agent.modules.scraper.tool.httpx.AsyncClient",
            return_value=client,
        ), patch(
            "giga_agent.modules.scraper.tool._summarize_page",
            AsyncMock(return_value={"url": "https://ok.example.com", "result": "ok"}),
        ):
            assert get_urls.coroutine is not None
            result = await get_urls.coroutine(
                urls=["https://ok.example.com", "not-a-url"],
                runtime=runtime,
                state=state,
            )

        self.assertEqual(len(result["results"]), 2)
        self.assertIn("result", result["results"][0])
        self.assertIn("error", result["results"][1])

    async def test_resolve_fast_llm_prefers_fast_llm_id_and_fallbacks_to_llm_id(self):
        runtime = self._runtime()

        @asynccontextmanager
        async def _session_context():
            yield object()

        llm_runtime = types.SimpleNamespace(llm=_FakeLLM())
        fast_id = uuid.uuid4()
        base_id = uuid.uuid4()

        with patch(
            "giga_agent.modules.scraper.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=types.SimpleNamespace(parallel_calls=3)),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ) as resolve_mock, patch(
            "giga_agent.modules.scraper.tool.UserRepository.get_cached_or_db",
            AsyncMock(
                return_value=types.SimpleNamespace(
                    id=uuid.uuid4(),
                    fast_llm_id=fast_id,
                    llm_id=base_id,
                )
            ),
        ):
            _, called_parallel_fast = await scraper_tool._resolve_fast_llm(runtime)
            called_fast = resolve_mock.await_args_list[-1].args[0]

        with patch(
            "giga_agent.modules.scraper.tool.get_session_factory",
            AsyncMock(return_value=lambda: _session_context()),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMRepository.get_cached_or_db",
            AsyncMock(return_value=types.SimpleNamespace(parallel_calls=1)),
        ), patch(
            "giga_agent.modules.scraper.tool.LLMManager.resolve_by_id",
            AsyncMock(return_value=llm_runtime),
        ) as resolve_mock, patch(
            "giga_agent.modules.scraper.tool.UserRepository.get_cached_or_db",
            AsyncMock(
                return_value=types.SimpleNamespace(
                    id=uuid.uuid4(),
                    fast_llm_id=None,
                    llm_id=base_id,
                )
            ),
        ):
            _, called_parallel_base = await scraper_tool._resolve_fast_llm(runtime)
            called_base = resolve_mock.await_args_list[-1].args[0]

        self.assertEqual(called_fast, fast_id)
        self.assertEqual(called_base, base_id)
        self.assertEqual(called_parallel_fast, 3)
        self.assertEqual(called_parallel_base, 1)
